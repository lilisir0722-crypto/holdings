"""技术分析流水线：页面、收盘记账、盘前推送共用，避免三套各拉各的。

mode=full：完整上下文 + LLM（技术页 / 收盘）。
mode=plan：日 K + 预案 + 外部参照，不跑 LLM（盘前推送，要快）。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from holdings.journal import backfill_outcomes, record_snapshot
from holdings.log import get_logger
from holdings.market import (
    fetch_eastmoney_etf,
    fetch_fund_gmbd,
    fetch_kline,
    fetch_market_context,
    fetch_xdxr,
    open_mac_client,
    to_snapshot,
)
from holdings.overseas import attach_overseas
from holdings.plan import PlanView, build_plan, build_tomorrow
from holdings.store import Holding, Store
from holdings.tech import (
    TechReport,
    analyze_chanlun,
    analyze_kline,
    attach_market_context,
    enrich_with_account,
)
from holdings.tech_extra import attach_tech_extras, is_listed_etf

log = get_logger("pipeline")


@dataclass
class TechRun:
    code: str
    name: str
    kind: str
    price: float | None
    report: TechReport | None = None
    plan: PlanView | None = None
    kdf: object = None
    payload: dict = field(default_factory=dict)
    error: str | None = None
    elapsed: float = 0.0


def _empty_ctx() -> dict:
    return {
        "capital_df": None,
        "belong_df": None,
        "board_summaries": {},
        "unusual_df": None,
        "board_names": {},
    }


def _fetch_ctx(code: str, kind: str, *, extras: bool) -> tuple[object, dict]:
    ctx: dict = _empty_ctx()
    with open_mac_client() as client:
        kdf = fetch_kline(code, kind, client=client)
        if extras:
            try:
                ctx = fetch_market_context(client, code)
            except Exception as exc:
                log.warning("%s 市场上下文拉取失败：%s", code, exc)
                ctx = _empty_ctx()
    if ctx is None:
        ctx = _empty_ctx()
    ctx["daily_df"] = kdf
    if extras:
        try:
            ctx["xdxr_df"] = fetch_xdxr(code)
        except Exception as exc:
            log.info("%s 除权数据拉取失败：%s", code, exc)
            ctx["xdxr_df"] = None
        if is_listed_etf(code):
            try:
                ctx["etf"] = fetch_eastmoney_etf(code)
            except Exception as exc:
                log.info("%s ETF 数据拉取失败：%s", code, exc)
                ctx["etf"] = {}
            try:
                ctx["etf_gmbd"] = fetch_fund_gmbd(code)
            except Exception as exc:
                log.info("%s 份额变动拉取失败：%s", code, exc)
                ctx["etf_gmbd"] = None
    return kdf, ctx


def _build_payload(name, code, price, cost, report, plan, cash_total, market_quote) -> dict:
    payload = {
        "名称": name,
        "代码": code,
        "现价": price,
        "成本": cost,
        "走势数据": report.trend_evidence,
        "对照数据": [{"方法": g.title, "数据": g.evidence} for g in report.guides],
        "多周期数据": report.timeframes.evidence if report.timeframes else None,
        "相对强弱数据": report.relative.evidence if report.relative else None,
        "分时数据": report.intraday.evidence if report.intraday else None,
        "除权数据": report.xdxr.evidence if report.xdxr else None,
        "ETF数据": report.etf.evidence if report.etf else None,
        "外部数据": report.overseas.evidence if report.overseas else None,
        "指标数值": [
            {"指标": s.name, "指标说明": s.about, "数值": s.evidence}
            for s in report.signals
        ],
        "无信号指标数值": [
            {"指标": s.name, "指标说明": s.about, "数值": s.evidence}
            for s in report.quiet
        ],
        "可用现金": cash_total,
    }
    if market_quote:
        payload["大盘数据"] = {
            "名称": market_quote.get("name") or "沪深300",
            "现价": market_quote.get("price"),
            "今日涨跌幅": market_quote.get("day_change_pct"),
            "近20日涨跌幅": market_quote.get("change_20d_pct"),
        }
    if report.capital:
        payload["资金数据"] = [report.capital.title, *report.capital.evidence]
    if report.boards:
        payload["板块数据"] = [
            {"板块": b.title, "数据": b.evidence} for b in report.boards
        ]
    if report.unusual:
        payload["异动数据"] = [report.unusual.title, *report.unusual.evidence[:20]]
    if report.chanlun:
        payload["缠论数据"] = {
            "统计": report.chanlun.counts,
            "买卖点": report.chanlun.mmds[-8:] if report.chanlun.mmds else [],
            "中枢": [
                {
                    "上沿": z.get("zg"),
                    "下沿": z.get("zd"),
                    "起": z.get("start_date"),
                    "止": z.get("end_date"),
                }
                for z in (report.chanlun.zss or [])[-3:]
                if isinstance(z, dict)
            ],
            "背驰": [
                {"类型": b.get("type"), "日期": b.get("curr_date"), "说明": b.get("msg")}
                for b in (report.chanlun.bcs or [])[-4:]
                if isinstance(b, dict)
            ],
        }
    if plan and plan.has:
        payload["关键点位"] = [f"{d.level}（{d.label}）" for d in plan.defenses]
    return payload


def run_tech(
    store: Store,
    hit: Holding,
    holdings: list[Holding] | None = None,
    *,
    mode: str = "full",
) -> TechRun:
    """跑一只的技术分析。失败时 TechRun.error 有说明，不抛给调用方。"""
    code = hit.code.strip()
    price = None
    if hit.quote and hit.quote.get("price") is not None:
        price = hit.quote["price"]
    name = (hit.quote or {}).get("name") or hit.name or code
    run = TechRun(code=code, name=name, kind=hit.kind, price=price)
    extras = mode == "full"
    t0 = time.monotonic()
    try:
        kdf, ctx = _fetch_ctx(code, hit.kind, extras=extras)
    except Exception as exc:
        log.warning("%s 行情拉取失败：%s", code, exc)
        run.error = f"行情连不上：{exc}"
        run.elapsed = time.monotonic() - t0
        return run
    run.kdf = kdf
    holdings = holdings if holdings is not None else store.list()
    cash = store.load_cash()
    snaps = [to_snapshot(h, h.quote) for h in holdings]
    book = sum((s.quantity * s.price) for s in snaps if s.price is not None)
    boards = list((ctx.get("board_names") or {}).values())

    if kdf is None or getattr(kdf, "empty", True):
        report = TechReport(
            stance="这只没有够用的日 K，算不了技术指标。",
            stance_evidence=["日 K 为空或场外基金走净值，没有交易所日 K"],
            signals=[],
            quiet=[],
        )
        if extras:
            report = attach_market_context(report, ctx, code=code)
            report = attach_tech_extras(report, ctx, code=code)
        report = attach_overseas(report, name=name, boards=boards)
        report.chanlun = analyze_chanlun(None, code)
        run.report = report
        run.elapsed = time.monotonic() - t0
        return run

    try:
        report = analyze_kline(kdf)
    except Exception as exc:
        log.warning("%s 指标计算失败：%s", code, exc)
        run.error = f"指标算不出来：{exc}"
        run.elapsed = time.monotonic() - t0
        return run

    pos_v = (hit.quantity * price) if price is not None else 0.0
    report = enrich_with_account(
        report,
        cash_total=cash.total,
        cash_known=cash.known,
        position_value=pos_v,
        book_value=book,
        cost=hit.cost,
        price=price,
    )
    if extras:
        report = attach_market_context(report, ctx, code=code)
        report = attach_tech_extras(report, ctx, code=code)
    report = attach_overseas(report, name=name, boards=boards)
    report.chanlun = analyze_chanlun(kdf, code)
    plan = build_plan(
        kdf,
        report.chanlun.fractals if report.chanlun and report.chanlun.ok else None,
        cost=hit.cost,
        cash_total=cash.total if cash.known else None,
        book_value=book,
    )
    run.plan = plan
    run.report = report
    if plan and plan.has:
        plan.tomorrow = build_tomorrow(plan, overseas=report.overseas)
    if mode == "full":
        from holdings.llm import explain_tech

        payload = _build_payload(
            name,
            code,
            price,
            hit.cost,
            report,
            plan,
            cash.total if cash.known else None,
            store.load_market(),
        )
        note, status = explain_tech(payload)
        report.model_note = note
        report.model_status = status
        run.payload = payload
    run.elapsed = time.monotonic() - t0
    log.info(
        "%s 分析完成（mode=%s，耗时 %.1fs，说明状态 %s）",
        code,
        mode,
        run.elapsed,
        getattr(run.report, "model_status", "") or "-",
    )
    return run


def persist_run(run: TechRun, hit: Holding, *, source: str = "page") -> bool:
    """记快照 + 回填事后。失败只打日志。"""
    if run.error or run.report is None:
        return False
    wrote = False
    try:
        plan = run.plan
        wrote = record_snapshot(
            run.code,
            name=run.name,
            price=run.price,
            cost=hit.cost,
            stance=run.report.stance,
            trend=run.report.trend_title,
            note=run.report.model_note or "",
            note_status=run.report.model_status or "",
            overseas_title=run.report.overseas.title if run.report.overseas else "",
            defenses=[{"level": d.level, "label": d.label} for d in plan.defenses]
            if plan and plan.has
            else [],
            confirm=plan.confirm if plan and plan.has else "",
            tomorrow=plan.tomorrow.title if plan and plan.tomorrow else "",
            payload=run.payload,
            source=source,
        )
    except Exception as exc:
        log.warning("%s 快照写入失败：%s", run.code, exc)
    try:
        n = backfill_outcomes(run.code, run.kdf)
        if n:
            log.info("%s 回填事后数据 %d 条", run.code, n)
    except Exception as exc:
        log.warning("%s 事后回填失败：%s", run.code, exc)
    return wrote
