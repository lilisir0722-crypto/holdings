from __future__ import annotations

import webbrowser
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import uvicorn
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from holdings.judge import judge_all, look_one
from holdings.market import (
    fetch_all,
    fetch_kline,
    fetch_one,
    open_mac_client,
    to_market_snapshot,
    to_snapshot,
)
from holdings.store import CashBook, Holding, Store
from holdings.tech import analyze_chanlun
from holdings.check import check_trade
from holdings.journal import (
    load_checks,
    load_journal,
    mark_followed,
    note_bucket,
    record_check,
    stance_bucket,
    summarize_split,
)
from holdings.jobs import job_close, job_open
from holdings.log import get_logger
from holdings.pipeline import persist_run, run_tech
from holdings.plan import build_plan

DATA = Path.cwd() / "data" / "holdings.json"
TEMPLATES = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))

log = get_logger("web")
store = Store(DATA)
app = FastAPI(title="持仓")

_BEIJING = ZoneInfo("Asia/Shanghai")


def format_beijing(raw) -> str:
    """UTC/带时区的 ISO 时间 → 北京时间 'YYYY-MM-DD HH:MM:SS'。解析不了就原样返回。"""
    if not raw:
        return ""
    if isinstance(raw, datetime):
        dt = raw
    else:
        try:
            dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except ValueError:
            return str(raw)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(_BEIJING).strftime("%Y-%m-%d %H:%M:%S")


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
            fetched_at = format_beijing(h.quote["fetched_at"])
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
    run = run_tech(store, hit, holdings, mode="full")
    if run.error and run.report is None:
        return TEMPLATES.TemplateResponse(
            request,
            "tech.html",
            {
                "error": run.error,
                "code": code,
                "name": run.name,
                "kind": hit.kind,
                "price": run.price,
                "report": None,
            },
        )
    persist_run(run, hit, source="page")
    return TEMPLATES.TemplateResponse(
        request,
        "tech.html",
        {
            "error": None,
            "code": code,
            "name": run.name,
            "kind": hit.kind,
            "price": run.price,
            "report": run.report,
            "plan": run.plan,
        },
    )


@app.post("/check/{code}")
def check(
    request: Request,
    code: str,
    side: str = Form(...),
    price: float = Form(...),
    qty: float = Form(...),
):
    holdings = store.list()
    hit = next((h for h in holdings if h.code.strip() == code), None)
    if hit is None:
        return TEMPLATES.TemplateResponse(
            request,
            "check.html",
            {
                "code": code,
                "name": code,
                "error": "这只不在你已经填进来的持仓里。",
                "result": None,
                "plan": None,
            },
            status_code=404,
        )
    name = (hit.quote or {}).get("name") or hit.name or code
    try:
        with open_mac_client() as client:
            kdf = fetch_kline(code, hit.kind, client=client)
        chanlun = analyze_chanlun(kdf, code)
        cash = store.load_cash()
        snaps = [to_snapshot(h, h.quote) for h in holdings]
        book = sum((s.quantity * s.price) for s in snaps if s.price is not None)
        plan = build_plan(
            kdf,
            chanlun.fractals if chanlun and chanlun.ok else None,
            cost=hit.cost,
            cash_total=cash.total if cash.known else None,
            book_value=book,
        )
        result = check_trade(
            side=side,
            price=price,
            qty=qty,
            plan=plan,
            cash=cash.total if cash.known else None,
            book=book,
            hold_qty=hit.quantity,
            cost=hit.cost,
            journals=load_journal(code, limit=5),
        )
        check_id = record_check(
            code,
            side=result.side,
            price=result.price,
            qty=result.qty,
            verdict=result.verdict,
            title=result.title,
            reasons=result.reasons,
            past=result.past,
        )
    except Exception as exc:
        log.warning("纪律检查 %s 失败：%s", code, exc)
        return TEMPLATES.TemplateResponse(
            request,
            "check.html",
            {
                "code": code,
                "name": name,
                "error": f"对照失败：{exc}",
                "result": None,
                "plan": None,
            },
        )
    return TEMPLATES.TemplateResponse(
        request,
        "check.html",
        {
            "code": code,
            "name": name,
            "error": None,
            "result": result,
            "plan": plan,
            "spot": (hit.quote or {}).get("price"),
            "check_id": check_id,
            "followed": None,
        },
    )


@app.post("/check/{code}/follow")
def check_follow(
    request: Request,
    code: str,
    check_id: str = Form(...),
    followed: str = Form(...),
):
    yes = followed in ("yes", "1", "true", "听了")
    mark_followed(code, check_id, yes)
    holdings = store.list()
    hit = next((h for h in holdings if h.code.strip() == code), None)
    name = ((hit.quote or {}).get("name") or hit.name) if hit else code
    recs = [c for c in load_checks(code, limit=20) if c.get("id") == check_id]
    rec = recs[0] if recs else {}
    return TEMPLATES.TemplateResponse(
        request,
        "check.html",
        {
            "code": code,
            "name": name,
            "error": None,
            "result": None,
            "plan": None,
            "check_id": check_id,
            "followed": rec.get("followed"),
            "follow_note": "已记下：听了。" if yes else "已记下：没听，还是下了。",
            "spot": (hit.quote or {}).get("price") if hit else None,
        },
    )


@app.get("/journal/{code}")
def journal(request: Request, code: str):
    holdings = store.list()
    hit = next((h for h in holdings if h.code.strip() == code), None)
    name = ((hit.quote or {}).get("name") or hit.name) if hit else code
    records = load_journal(code)
    for r in records:
        r["rule_bucket"] = stance_bucket(r.get("stance") or "")
        r["note_bucket"] = (
            note_bucket(r.get("note") or "") if (r.get("note_status") or "") == "ok" else ""
        )
    split = summarize_split(records)
    return TEMPLATES.TemplateResponse(
        request,
        "journal.html",
        {
            "code": code,
            "name": name,
            "records": records,
            "summary_rules": split["规则"],
            "summary_notes": split["说明"],
            "checks": load_checks(code),
        },
    )


@app.post("/jobs/close")
def jobs_close(request: Request):
    out = job_close(store)
    return TEMPLATES.TemplateResponse(
        request, "jobs.html", {"title": "收盘记账", "result": out}
    )


@app.post("/jobs/open")
def jobs_open(request: Request):
    out = job_open(store)
    return TEMPLATES.TemplateResponse(
        request, "jobs.html", {"title": "盘前推送", "result": out}
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
