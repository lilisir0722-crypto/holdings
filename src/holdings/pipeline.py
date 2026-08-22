"""技术分析流水线：页面、收盘记账、盘前推送共用，避免三套各拉各的。

mode=full：完整上下文 + LLM（技术页 / 收盘）。
mode=plan：日 K + 预案 + 外部参照，不跑 LLM（盘前推送，要快）。
"""

from __future__ import annotations

import threading
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
    attach_main_intent,
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
    extras_done: bool = False


_PAGE_RUNS: dict[str, TechRun] = {}
_PAGE_LOCK = threading.Lock()


def remember_run(run: TechRun) -> None:
    with _PAGE_LOCK:
        _PAGE_RUNS[run.code] = run


def recall_run(code: str) -> TechRun | None:
    with _PAGE_LOCK:
        return _PAGE_RUNS.get(code.strip())


def clear_page_runs() -> None:
    with _PAGE_LOCK:
        _PAGE_RUNS.clear()


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
        _fill_xdxr_etf(ctx, code)
        _fill_capital_history(ctx, code)
    return kdf, ctx


def _fill_xdxr_etf(ctx: dict, code: str) -> None:
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


def _fetch_extras_ctx(code: str, kdf) -> dict:
    ctx: dict = _empty_ctx()
    try:
        with open_mac_client() as client:
            try:
                fetched = fetch_market_context(client, code)
                if fetched:
                    ctx = fetched
            except Exception as exc:
                log.warning("%s 市场上下文拉取失败：%s", code, exc)
                ctx = _empty_ctx()
    except Exception as exc:
        log.warning("%s 外部行情客户端失败：%s", code, exc)
    if ctx is None:
        ctx = _empty_ctx()
    ctx["daily_df"] = kdf
    _fill_xdxr_etf(ctx, code)
    _fill_capital_history(ctx, code)
    return ctx


def _fill_capital_history(ctx: dict, code: str) -> None:
    """通达信当日资金写入 data/fflow/{code}.json，页面用本地攒下的历史。"""
    from holdings.fflow import to_frame, upsert_snapshot

    try:
        rows = upsert_snapshot(code, ctx.get("capital_df"))
    except Exception as exc:
        log.info("%s 资金流向本地库失败：%s", code, exc)
        rows = []
    ctx["capital_df"] = to_frame(rows) if rows else None


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
    if report.intent:
        payload["主力意图"] = [report.intent.title, *report.intent.evidence]
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


def _set_payload(run: TechRun, store: Store, hit: Holding) -> None:
    if run.report is None:
        run.payload = {}
        return
    cash = store.load_cash()
    run.payload = _build_payload(
        run.name,
        run.code,
        run.price,
        hit.cost,
        run.report,
        run.plan,
        cash.total if cash.known else None,
        store.load_market(),
    )


def fill_overseas(run: TechRun, *, boards: list | None = None) -> TechRun:
    if run.report is None:
        return run
    run.report = attach_overseas(run.report, name=run.name, boards=boards or [])
    if run.plan and run.plan.has:
        run.plan.tomorrow = build_tomorrow(run.plan, overseas=run.report.overseas)
    return run


def fill_extras(run: TechRun, store: Store, hit: Holding) -> TechRun:
    if run.report is None:
        return run
    ctx = _fetch_extras_ctx(run.code, run.kdf)
    run.report = attach_market_context(run.report, ctx, code=run.code)
    run.report = attach_tech_extras(run.report, ctx, code=run.code)
    run.report = attach_main_intent(run.report, ctx)
    boards = list((ctx.get("board_names") or {}).values())
    fill_overseas(run, boards=boards)
    run.extras_done = True
    _set_payload(run, store, hit)
    return run


def fill_note(run: TechRun, store: Store, hit: Holding) -> TechRun:
    from holdings.llm import explain_tech

    if run.report is None:
        return run
    _set_payload(run, store, hit)
    note, status = explain_tech(run.payload)
    run.report.model_note = note
    run.report.model_status = status
    return run


def run_tech(
    store: Store,
    hit: Holding,
    holdings: list[Holding] | None = None,
    *,
    mode: str = "full",
) -> TechRun:
    """跑一只的技术分析。失败时 TechRun.error 有说明，不抛给调用方。

    mode=core：日 K、指标、预案、缠论。
    mode=plan：core + 外部参照（盘前）。
    mode=full：core + 外部/资金/ETF + LLM（收盘记账）。
    """
    run = _run_core(store, hit, holdings)
    if run.error and run.report is None:
        return run
    if mode == "core":
        _set_payload(run, store, hit)
        return run
    if mode == "plan":
        fill_overseas(run)
        _set_payload(run, store, hit)
        return run
    fill_extras(run, store, hit)
    fill_note(run, store, hit)
    return run


def _run_core(
    store: Store,
    hit: Holding,
    holdings: list[Holding] | None = None,
) -> TechRun:
    code = hit.code.strip()
    price = None
    if hit.quote and hit.quote.get("price") is not None:
        price = hit.quote["price"]
    name = (hit.quote or {}).get("name") or hit.name or code
    run = TechRun(code=code, name=name, kind=hit.kind, price=price)
    t0 = time.monotonic()
    try:
        kdf, _ctx = _fetch_ctx(code, hit.kind, extras=False)
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

    if kdf is None or getattr(kdf, "empty", True):
        report = TechReport(
            stance="这只没有够用的日 K，算不了技术指标。",
            stance_evidence=["日 K 为空或场外基金走净值，没有交易所日 K"],
            signals=[],
            quiet=[],
        )
        report.chanlun = analyze_chanlun(None, code)
        run.report = report
        run.elapsed = time.monotonic() - t0
        log.info("%s 分析完成（mode=core，耗时 %.1fs，无日 K）", code, run.elapsed)
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
    report.chanlun = analyze_chanlun(kdf, code)
    plan = build_plan(
        kdf,
        report.chanlun.fractals if report.chanlun and report.chanlun.ok else None,
        cost=hit.cost,
        cash_total=cash.total if cash.known else None,
        book_value=book,
    )
    if plan and plan.has:
        plan.tomorrow = build_tomorrow(plan, overseas=None)
    run.plan = plan
    run.report = report
    run.elapsed = time.monotonic() - t0
    log.info("%s 分析完成（mode=core，耗时 %.1fs）", code, run.elapsed)
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
