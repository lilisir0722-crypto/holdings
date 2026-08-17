from __future__ import annotations

import webbrowser
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from holdings.judge import judge_all, look_one
from holdings.market import (
    fetch_all,
    fetch_eastmoney_etf,
    fetch_kline,
    fetch_market_context,
    fetch_one,
    fetch_xdxr,
    open_mac_client,
    to_market_snapshot,
    to_snapshot,
)
from holdings.store import CashBook, Holding, Store
from holdings.tech import (
    TechReport,
    analyze_chanlun,
    analyze_kline,
    attach_market_context,
    enrich_with_account,
)
from holdings.tech_extra import attach_tech_extras, is_listed_etf

DATA = Path.cwd() / "data" / "holdings.json"
TEMPLATES = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))

store = Store(DATA)
app = FastAPI(title="持仓")


def _page(
    request: Request,
    error: str | None = None,
    refreshing: bool = False,
    look=None,
    look_snapshot=None,
):
    holdings = store.list()
    snapshots = [to_snapshot(h, h.quote) for h in holdings]
    market = to_market_snapshot(store.load_market())
    cash = store.load_cash()
    report = judge_all(snapshots, market=market, cash=cash)
    fetched_at = None
    for h in holdings:
        if h.quote and h.quote.get("fetched_at"):
            fetched_at = h.quote["fetched_at"]
            break
    return TEMPLATES.TemplateResponse(
        request,
        "index.html",
        {
            "holdings": holdings,
            "report": report,
            "error": error,
            "fetched_at": fetched_at,
            "refreshing": refreshing,
            "look": look,
            "look_snapshot": look_snapshot,
            "cash": cash,
        },
    )


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return _page(request)


@app.post("/add")
def add(
    kind: str = Form(...),
    code: str = Form(...),
    quantity: float = Form(...),
    cost: float = Form(...),
    name: str = Form(""),
    place: str = Form("佣金宝"),
):
    code = code.strip()
    store.add(
        Holding(
            kind=kind,
            code=code,
            name=name.strip() or code,
            quantity=quantity,
            cost=cost,
            place=place.strip() or "佣金宝",
        )
    )
    return RedirectResponse("/", status_code=303)


@app.post("/delete/{item_id}")
def delete(item_id: str):
    store.delete(item_id)
    return RedirectResponse("/", status_code=303)


@app.post("/cash")
def set_cash(
    yongjinbao: str = Form("0"),
    alipay: str = Form("0"),
):
    def _num(raw: str) -> float:
        raw = (raw or "").strip()
        if not raw:
            return 0.0
        return float(raw)

    store.save_cash(
        CashBook(
            yongjinbao=_num(yongjinbao),
            alipay=_num(alipay),
            updated_at="",  # save_cash fills timestamp
        )
    )
    return RedirectResponse("/", status_code=303)


@app.post("/look")
def look(
    request: Request,
    kind: str = Form(...),
    code: str = Form(...),
    quantity: str = Form(""),
):
    code = code.strip()
    holdings = store.list()
    snapshots = [to_snapshot(h, h.quote) for h in holdings]
    market = to_market_snapshot(store.load_market())
    try:
        quote = fetch_one(kind, code)
    except Exception as exc:
        return _page(request, error=f"行情连不上：{exc}")
    qty = 0.0
    if quantity.strip():
        try:
            qty = float(quantity)
        except ValueError:
            qty = 0.0
    stub = Holding(kind=kind, code=code, name=quote.get("name") or code, quantity=qty, cost=0)
    snap = to_snapshot(stub, quote)
    return _page(request, look=look_one(snap, snapshots, market), look_snapshot=snap)


@app.get("/tech/{code}", response_class=HTMLResponse)
def tech(request: Request, code: str):
    code = code.strip()
    holdings = store.list()
    hit = next((h for h in holdings if h.code.strip() == code), None)
    if hit is None:
        return TEMPLATES.TemplateResponse(
            request,
            "tech.html",
            {"error": "这只不在你已经填进来的持仓里。", "code": code, "name": code, "kind": "", "price": None, "report": None},
            status_code=404,
        )
    price = None
    if hit.quote and hit.quote.get("price") is not None:
        price = hit.quote["price"]
    name = (hit.quote or {}).get("name") or hit.name or code

    ctx: dict | None = None
    try:
        with open_mac_client() as client:
            kdf = fetch_kline(code, hit.kind, client=client)
            try:
                ctx = fetch_market_context(client, code)
            except Exception:
                ctx = {"capital_df": None, "belong_df": None, "board_summaries": {}, "unusual_df": None}
        if ctx is None:
            ctx = {}
        ctx["daily_df"] = kdf
        try:
            ctx["xdxr_df"] = fetch_xdxr(code)
        except Exception:
            ctx["xdxr_df"] = None
        if is_listed_etf(code):
            try:
                ctx["etf"] = fetch_eastmoney_etf(code)
            except Exception:
                ctx["etf"] = {}
    except Exception as exc:
        return TEMPLATES.TemplateResponse(
            request,
            "tech.html",
            {
                "error": f"行情连不上：{exc}",
                "code": code,
                "name": name,
                "kind": hit.kind,
                "price": price,
                "report": None,
            },
        )
    if kdf is None or getattr(kdf, "empty", True):
        empty = TechReport(
            stance="这只没有够用的日 K，算不了技术指标。",
            stance_evidence=["日 K 为空或场外基金走净值，没有交易所日 K"],
            signals=[],
            quiet=[],
        )
        empty = attach_market_context(empty, ctx, code=code)
        empty = attach_tech_extras(empty, ctx, code=code)
        empty.chanlun = analyze_chanlun(None, code)
        return TEMPLATES.TemplateResponse(
            request,
            "tech.html",
            {
                "error": None,
                "code": code,
                "name": name,
                "kind": hit.kind,
                "price": price,
                "report": empty,
            },
        )
    try:
        report = analyze_kline(kdf)
    except Exception as exc:
        return TEMPLATES.TemplateResponse(
            request,
            "tech.html",
            {
                "error": f"指标算不出来：{exc}",
                "code": code,
                "name": name,
                "kind": hit.kind,
                "price": price,
                "report": None,
            },
        )
    cash = store.load_cash()
    snaps = [to_snapshot(h, h.quote) for h in holdings]
    book = sum((s.quantity * s.price) for s in snaps if s.price is not None)
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
    report = enrich_with_account(
        report,
        cash_total=cash.total,
        cash_known=cash.known,
        position_value=pos_v,
        book_value=book,
        cost=hit.cost,
        price=price,
    )
    report = attach_market_context(report, ctx, code=code)
    report = attach_tech_extras(report, ctx, code=code)
    report.chanlun = analyze_chanlun(kdf, code)
    from holdings.llm import explain_tech

    payload = {
        "名称": name,
        "代码": code,
        "现价": price,
        "成本": hit.cost,
        "总倾向": report.stance,
        "总倾向依据": report.stance_evidence,
        "走势": report.trend_title,
        "走势依据": report.trend_evidence,
        "对照": [{"标题": g.title, "依据": g.evidence} for g in report.guides],
        "多周期": report.timeframes.title if report.timeframes else None,
        "相对强弱": report.relative.title if report.relative else None,
        "分时": report.intraday.title if report.intraday else None,
        "除权": report.xdxr.title if report.xdxr else None,
        "ETF": report.etf.title if report.etf else None,
        "有信号": [
            {"指标": s.name, "解读": s.reading, "依据": s.evidence} for s in report.signals
        ],
        "可用现金": cash.total if cash.known else None,
        "现金已填": cash.known,
    }
    if report.capital:
        payload["资金"] = report.capital.title
        if report.capital.summary_line:
            payload["资金摘要"] = report.capital.summary_line
    if report.boards:
        payload["板块"] = [
            {"标题": b.title, "摘要": b.summary_line, "依据": b.evidence}
            for b in report.boards
        ]
    if report.unusual:
        payload["异动"] = {
            "标题": report.unusual.title,
            "依据": report.unusual.evidence[:20],
        }
    if report.chanlun:
        payload["缠论"] = {
            "标题": report.chanlun.title,
            "统计": report.chanlun.counts,
            "买卖点": report.chanlun.mmds[-8:] if report.chanlun.mmds else [],
            "说明": report.chanlun.note,
        }
    note, status = explain_tech(payload)
    report.model_note = note
    report.model_status = status
    return TEMPLATES.TemplateResponse(
        request,
        "tech.html",
        {
            "error": None,
            "code": code,
            "name": name,
            "kind": hit.kind,
            "price": price,
            "report": report,
        },
    )


@app.post("/refresh")
def refresh(request: Request):
    holdings = store.list()
    try:
        quotes, market = fetch_all(holdings)
        store.save_quotes(quotes)
        store.save_market(market)
        return RedirectResponse("/", status_code=303)
    except Exception as exc:
        return _page(request, error=f"行情连不上：{exc}")


def main() -> None:
    DATA.parent.mkdir(parents=True, exist_ok=True)
    webbrowser.open("http://127.0.0.1:8765")
    uvicorn.run("holdings.web:app", host="127.0.0.1", port=8765, reload=False)
