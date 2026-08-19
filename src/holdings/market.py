from __future__ import annotations

import json
import re
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone

from easy_tdx import MacClient, Market, ping_mac_all
from easy_tdx.cninfo import CninfoClient
from easy_tdx.config import get_mac_hosts, get_port, save_best_mac_host
from easy_tdx.mac.enums import Adjust, BoardType, Period

from holdings.judge import MarketSnapshot, PositionSnapshot
from holdings.store import Holding


def rank_mac_hosts(
    hosts: list[str], ranked: list[tuple[str, float]] | None = None
) -> list[str]:
    """Fastest ping first; append any host that did not answer the ping."""
    order: list[str] = []
    seen: set[str] = set()
    sorted_ranked = sorted(ranked or [], key=lambda row: row[1])
    for host, _lat in sorted_ranked:
        if host in hosts and host not in seen:
            order.append(host)
            seen.add(host)
    for host in hosts:
        if host not in seen:
            order.append(host)
            seen.add(host)
    return order


def _is_connect_error(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return any(
        w in msg
        for w in ("timed out", "timeout", "无法连接", "connection", "refused", "reset", "断")
    )


@contextmanager
def open_mac_client(timeout: float = 10.0, ping_timeout: float = 2.5):
    """Connect to a working MAC quote host; try others if one times out."""
    hosts = list(get_mac_hosts())
    try:
        ranked = ping_mac_all(hosts, get_port(), ping_timeout)
    except Exception:
        ranked = []
    order = rank_mac_hosts(hosts, ranked)
    last: BaseException | None = None
    client: MacClient | None = None
    for host in order:
        try:
            client = MacClient(host, timeout=timeout)
            client.connect()
            try:
                save_best_mac_host(host)
            except Exception:
                pass
            break
        except Exception as exc:
            last = exc
            client = None
            if not _is_connect_error(exc):
                # unexpected error on this host — still try next
                continue
    if client is None:
        detail = str(last) if last else "没有可用主机"
        raise RuntimeError(
            f"行情服务器连不上（已换机重试）。{detail}。请稍后再点刷新。"
        ) from last
    try:
        yield client
    finally:
        try:
            client.close()
        except Exception:
            pass


def kline_window_after_jumps(df, jump: float = 0.4):
    if df is None or df.empty:
        return df
    ordered = df.sort_values("datetime").reset_index(drop=True)
    closes = ordered["close"].astype(float)
    start = 0
    for i in range(1, len(closes)):
        prev = float(closes.iloc[i - 1])
        cur = float(closes.iloc[i])
        if prev > 0 and abs(cur / prev - 1) >= jump:
            start = i
    return ordered.iloc[start:]


def split_adjusted_closes(df, jump: float = 0.4) -> list[float]:
    if df is None or df.empty or "close" not in df.columns:
        return []
    ordered = df.sort_values("datetime").reset_index(drop=True)
    closes = [float(x) for x in ordered["close"].tolist()]
    n = len(closes)
    factors = [1.0] * n
    for i in range(n - 1, 0, -1):
        prev, cur = closes[i - 1], closes[i]
        if prev > 0 and abs(cur / prev - 1) >= jump:
            ratio = cur / prev
            for j in range(i):
                factors[j] *= ratio
    return [c * f for c, f in zip(closes, factors)]


def daily_returns_from_kline(df, jump: float = 0.4) -> list[float]:
    closes = split_adjusted_closes(df, jump)
    rets: list[float] = []
    for i in range(1, len(closes)):
        prev = closes[i - 1]
        if prev:
            rets.append(closes[i] / prev - 1)
    return rets


def split_adjusted_peak(df, jump: float = 0.4):
    if df is None or df.empty or "close" not in df.columns:
        return None, None, None, None
    ordered = df.sort_values("datetime").reset_index(drop=True)
    adj = split_adjusted_closes(df, jump)
    if not adj:
        return None, None, None, None
    n = len(adj)
    peak_i = max(range(n), key=lambda i: adj[i])
    peak_price = adj[peak_i]
    raw = ordered.loc[peak_i, "datetime"]
    if hasattr(raw, "strftime"):
        peak_date = raw.strftime("%Y-%m-%d")
    else:
        peak_date = str(raw)[:10]
    last = adj[-1]
    drawdown = last / peak_price - 1 if peak_price else None
    return peak_price, peak_date, last, drawdown


def is_otc_fund(kind: str, code: str) -> bool:
    if kind != "基金":
        return False
    c = code.strip()
    if len(c) != 6 or not c.isdigit():
        return False
    return not c.startswith(("15", "16", "18", "50", "51", "52", "56", "58"))


def parse_eastmoney_otc_quote(raw: dict) -> dict:
    data = raw.get("data") or {}
    out: dict = {}
    price = data.get("f43")
    if isinstance(price, (int, float)):
        out["price"] = float(price)
    name = data.get("f58")
    if name and str(name).strip():
        out["name"] = str(name).strip()
    pre = data.get("f60")
    if isinstance(pre, (int, float)):
        out["pre_close"] = float(pre)
    chg = data.get("f170")
    if isinstance(chg, (int, float)):
        out["day_change_pct"] = float(chg) / 100.0
    return out


def fetch_eastmoney_otc(code: str) -> dict:
    url = (
        "https://push2.eastmoney.com/api/qt/stock/get"
        f"?invt=2&fltt=2&secid=150.{code}"
        "&fields=f43,f57,f58,f60,f170,f44,f45"
    )
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://quote.eastmoney.com/",
        },
    )
    with urllib.request.urlopen(req, timeout=8) as resp:
        raw = json.loads(resp.read().decode())
    return parse_eastmoney_otc_quote(raw)


def parse_fund_holdings(text: str) -> tuple[list[str], str | None]:
    asof = None
    m = re.search(r"截止至：<font[^>]*>([^<]+)</font>", text)
    if m:
        asof = m.group(1).strip()
    names = re.findall(r"<td class='tol'><a href='[^']+'>([^<]+)</a></td>", text)
    return names[:10], asof


def fetch_fund_holdings(code: str) -> tuple[list[str], str | None]:
    urls = [
        (
            "https://fundf10.eastmoney.com/FundArchivesDatas.aspx"
            f"?type=jjcc&code={code}&topline=10"
        ),
        (
            "http://fundf10.eastmoney.com/FundArchivesDatas.aspx"
            f"?type=jjcc&code={code}&topline=10"
        ),
    ]
    last_err: Exception | None = None
    for url in urls:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Referer": "https://fund.eastmoney.com/",
            },
        )
        for _ in range(2):
            try:
                with urllib.request.urlopen(req, timeout=12) as resp:
                    text = resp.read().decode("utf-8", "replace")
                names, asof = parse_fund_holdings(text)
                if names:
                    return names, asof
            except Exception as exc:
                last_err = exc
    if last_err:
        raise last_err
    return [], None


def infer_market(code: str) -> str:
    first = code.strip()[0]
    if first in "569":
        return "SH"
    return "SZ"


def _market_enum(code: str) -> int:
    return Market.SH if infer_market(code) == "SH" else Market.SZ


def _recent_announcements(code: str, days: int = 7) -> list[str]:
    try:
        client = CninfoClient()
        df = client.get_announcements(code, count=8)
    except Exception:
        return []
    if df is None or df.empty:
        return []
    cutoff = date.today() - timedelta(days=days)
    rows: list[str] = []
    for _, row in df.iterrows():
        raw_date = str(row.get("date", ""))
        title = str(row.get("title", "")).strip()
        if not title:
            continue
        try:
            d = datetime.strptime(raw_date[:10], "%Y-%m-%d").date()
        except ValueError:
            rows.append(f"{raw_date} {title}".strip())
            continue
        if d >= cutoff:
            rows.append(f"{d.isoformat()} {title}")
    return rows


def fetch_quote(
    client: MacClient,
    holding: Holding,
    *,
    with_announcements: bool = True,
    with_holdings: bool = False,
) -> dict:
    code = holding.code.strip()
    now = datetime.now(timezone.utc).isoformat()
    quote: dict = {
        "price": None,
        "name": holding.name,
        "pre_close": None,
        "day_change_pct": None,
        "high_120": None,
        "low_120": None,
        "change_20d_pct": None,
        "daily_returns": [],
        "announcements": [],
        "top_holdings": [],
        "holdings_asof": "",
        "error": None,
        "fetched_at": now,
        "code": code,
    }
    market = _market_enum(code)
    if is_otc_fund(holding.kind, code):
        try:
            otc = fetch_eastmoney_otc(code)
            quote.update(otc)
        except Exception as exc:
            quote["error"] = str(exc)
        if quote["price"] is None and not quote["error"]:
            quote["error"] = "没有净值"
        if with_holdings and holding.kind == "基金":
            try:
                names, asof = fetch_fund_holdings(code)
                quote["top_holdings"] = names
                quote["holdings_asof"] = asof or ""
            except Exception:
                pass
        return quote
    try:
        qdf = client.get_stock_quotes([(market, code)])
        if qdf is not None and not qdf.empty:
            row = qdf.iloc[0]
            close = row.get("close")
            pre = row.get("pre_close")
            name = row.get("name")
            if close is not None and close == close:
                quote["price"] = float(close)
            if pre is not None and pre == pre and pre and quote["price"] is not None:
                quote["pre_close"] = float(pre)
                quote["day_change_pct"] = (quote["price"] - float(pre)) / float(pre)
            if name and str(name).strip():
                quote["name"] = str(name).strip()
        kdf = client.get_stock_kline(market, code, period=Period.DAILY, count=120)
        if kdf is not None and not kdf.empty and "high" in kdf.columns:
            window = kline_window_after_jumps(kdf)
            quote["high_120"] = float(window["high"].max())
            quote["low_120"] = float(window["low"].min())
            if quote["price"] is None and "close" in window.columns:
                quote["price"] = float(window["close"].iloc[-1])
            ordered = kdf.sort_values("datetime")
            if len(ordered) >= 21:
                old = float(ordered["close"].iloc[-21])
                last = float(ordered["close"].iloc[-1])
                if old:
                    quote["change_20d_pct"] = last / old - 1
            quote["daily_returns"] = daily_returns_from_kline(kdf)
    except Exception as exc:
        quote["error"] = str(exc)

    if with_holdings and holding.kind == "基金":
        try:
            names, asof = fetch_fund_holdings(code)
            quote["top_holdings"] = names
            quote["holdings_asof"] = asof or ""
        except Exception:
            pass
    if with_announcements and not is_otc_fund(holding.kind, code):
        quote["announcements"] = _recent_announcements(code)
    if quote["price"] is None and not quote["error"]:
        quote["error"] = "没有净值" if is_otc_fund(holding.kind, code) else "没有行情"
    return quote


HS300_CODE = "510300"


def fetch_all(holdings: list[Holding]) -> tuple[dict[str, dict], dict]:
    with open_mac_client() as client:
        quotes = {h.code: fetch_quote(client, h) for h in holdings}
        index = Holding(
            kind="股票",
            code=HS300_CODE,
            name="沪深300",
            quantity=0,
            cost=0,
        )
        market = fetch_quote(client, index, with_announcements=False)
        market["name"] = "沪深300"
        return quotes, market


def fetch_one(kind: str, code: str, name: str = "") -> dict:
    holding = Holding(kind=kind, code=code, name=name or code, quantity=0, cost=0)
    with open_mac_client() as client:
        quote = fetch_quote(client, holding, with_holdings=False)
    if kind == "基金":
        try:
            names, asof = fetch_fund_holdings(code.strip())
            quote["top_holdings"] = names
            quote["holdings_asof"] = asof or ""
        except Exception:
            pass
    return quote


def _as_df(val):
    try:
        import pandas as pd

        if isinstance(val, pd.DataFrame):
            return val
    except Exception:
        return None
    return None


def _kline(client, market: int, code: str, period, count: int):
    try:
        return _as_df(
            client.get_stock_kline(
                market, code, period=period, count=count, adjust=Adjust.QFQ
            )
        )
    except Exception:
        return None


_RANK_TTL_SEC = 300.0
_rank_lock = threading.Lock()
_rank_cache: tuple[float, list, list] | None = None
_RANK_JOBS = (
    ("1d", BoardType.HY, 1),
    ("20d", BoardType.HY, 20),
    ("1d", BoardType.GN, 1),
    ("20d", BoardType.GN, 20),
)


def clear_board_rank_cache() -> None:
    global _rank_cache
    with _rank_lock:
        _rank_cache = None


def _rank_cache_get() -> tuple[list | None, list | None] | None:
    with _rank_lock:
        if _rank_cache is None:
            return None
        ts, ranks_1d, ranks_20d = _rank_cache
        if time.monotonic() - ts >= _RANK_TTL_SEC:
            return None
        return ranks_1d, ranks_20d


def _rank_cache_put(ranks_1d: list | None, ranks_20d: list | None) -> None:
    global _rank_cache
    if not ranks_1d and not ranks_20d:
        return
    with _rank_lock:
        _rank_cache = (time.monotonic(), ranks_1d, ranks_20d)


def _connect_mac(host: str, timeout: float = 10.0):
    client = MacClient(host, timeout=timeout)
    client.connect()
    return client


def _rank_one_on_client(client, btype, days: int):
    try:
        return _as_df(client.get_board_change_ranking(btype, days=days))
    except Exception:
        return None


def _rank_one_on_host(host: str, btype, days: int, timeout: float = 10.0):
    client = None
    try:
        client = _connect_mac(host, timeout=timeout)
        return _rank_one_on_client(client, btype, days)
    except Exception:
        return None
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:
                pass


def fetch_board_ranks(client) -> tuple[list | None, list | None]:
    """HY/GN × 1日/20日。有主机地址时各开一条连接并发；结果缓存 5 分钟。

    同一条 MAC 连接不能并行读写，所以并发必须另开连接，不能 ThreadPool 打同一个 client。
    """
    hit = _rank_cache_get()
    if hit is not None:
        return hit
    results: dict[tuple, object] = {}
    host = getattr(client, "_host", None)
    if isinstance(host, str) and host:
        with ThreadPoolExecutor(max_workers=4) as pool:
            futs = {
                pool.submit(_rank_one_on_host, host, btype, days): (bucket, btype, days)
                for bucket, btype, days in _RANK_JOBS
            }
            for fut, key in futs.items():
                results[key] = fut.result()
    else:
        for bucket, btype, days in _RANK_JOBS:
            results[(bucket, btype, days)] = _rank_one_on_client(client, btype, days)

    ranks_1d: list = []
    ranks_20d: list = []
    for bucket, btype, days in _RANK_JOBS:
        df = results.get((bucket, btype, days))
        if df is None:
            continue
        if bucket == "1d":
            ranks_1d.append(df)
        else:
            ranks_20d.append(df)
    out_1d = ranks_1d or None
    out_20d = ranks_20d or None
    _rank_cache_put(out_1d, out_20d)
    return out_1d, out_20d


def fetch_market_context(client, code: str) -> dict:
    """Return capital/board pieces; never raise for soft failures."""
    from holdings.tech import select_belong_boards

    out = {
        "capital_df": None,
        "belong_df": None,
        "board_summaries": {},
        "unusual_df": None,
        "weekly_df": None,
        "min60_df": None,
        "hs300_df": None,
        "board_klines": {},
        "board_names": {},
        "board_rank_1d": None,
        "board_rank_20d": None,
        "tick_df": None,
        "auction_df": None,
        "error": None,
    }
    try:
        market = _market_enum(code)
    except Exception as exc:
        out["error"] = str(exc)
        return out
    try:
        out["capital_df"] = client.get_capital_flow(market, code)
    except Exception as exc:
        out["error"] = str(exc)
    try:
        out["belong_df"] = client.get_belong_board(market, code)
    except Exception as exc:
        belong_err = f"belong: {exc}"
        out["error"] = belong_err if not out["error"] else f"{out['error']}; {belong_err}"

    summaries: dict = {}
    try:
        selected = select_belong_boards(out["belong_df"], limit=2)
    except Exception as exc:
        belong_err = f"belong: {exc}"
        out["error"] = belong_err if not out["error"] else f"{out['error']}; {belong_err}"
        selected = []
    for row in selected:
        board_code = row["board_code"]
        try:
            raw = client.get_board_summary(board_code)
            if not isinstance(raw, dict):
                continue
            summaries[board_code] = {
                k: v
                for k, v in raw.items()
                if k != "members"
                and k
                in (
                    "member_count",
                    "amount",
                    "vol",
                    "main_net_amount",
                    "main_net_3d",
                    "main_net_5d",
                    "up_count",
                    "down_count",
                )
            }
        except Exception:
            # Soft-fail per board; pick_boards will show 板块暂无
            continue
    out["board_summaries"] = summaries
    try:
        out["unusual_df"] = client.get_unusual(market)
    except Exception as exc:
        unusual_err = f"unusual: {exc}"
        out["error"] = unusual_err if not out["error"] else f"{out['error']}; {unusual_err}"

    out["weekly_df"] = _kline(client, market, code, Period.WEEKLY, 60)
    out["min60_df"] = _kline(client, market, code, Period.MIN_60, 80)
    out["hs300_df"] = _kline(client, Market.SH, HS300_CODE, Period.DAILY, 80)

    board_klines: dict = {}
    board_names: dict = {}
    for row in selected:
        bcode = row["board_code"]
        bdf = _kline(client, market, bcode, Period.DAILY, 80)
        if bdf is None:
            bdf = _kline(client, Market.SH, bcode, Period.DAILY, 80)
        if bdf is not None:
            board_klines[bcode] = bdf
            board_names[bcode] = row["board_name"]
    out["board_klines"] = board_klines
    out["board_names"] = board_names

    ranks_1d, ranks_20d = fetch_board_ranks(client)
    out["board_rank_1d"] = ranks_1d
    out["board_rank_20d"] = ranks_20d

    try:
        out["tick_df"] = _as_df(client.get_tick_chart(market, code))
    except Exception:
        out["tick_df"] = None
    try:
        out["auction_df"] = _as_df(client.get_auction(market, code))
    except Exception:
        out["auction_df"] = None
    return out


def fetch_xdxr(code: str):
    """除权除息。MacClient 没有，另开 TdxClient。失败返回 None。"""
    try:
        from easy_tdx import TdxClient

        client = TdxClient.from_best_host(timeout=8.0, ping_timeout=2.0)
        try:
            mkt = Market.SH if infer_market(code) == "SH" else Market.SZ
            return _as_df(client.get_xdxr_info(mkt, code.strip()))
        finally:
            client.close()
    except Exception:
        return None


def fetch_eastmoney_etf(code: str) -> dict:
    from holdings.tech_extra import parse_eastmoney_etf_quote

    market = 1 if infer_market(code) == "SH" else 0
    url = (
        "https://push2.eastmoney.com/api/qt/stock/get"
        f"?invt=2&fltt=2&secid={market}.{code.strip()}"
        "&fields=f43,f46,f58,f116,f117"
    )
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://quote.eastmoney.com/",
        },
    )
    with urllib.request.urlopen(req, timeout=8) as resp:
        raw = json.loads(resp.read().decode())
    return parse_eastmoney_etf_quote(raw)


def parse_fund_gmbd(html: str) -> list[dict]:
    """fundf10 规模变动页的表格 → [{date, subs, redm, shares, nav, change}]，最新在前。"""
    out: list[dict] = []
    for row in re.findall(r"<tr>(.*?)</tr>", html or "", re.S):
        cells = [
            re.sub(r"<[^>]+>", "", c).strip()
            for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)
        ]
        if len(cells) != 6 or not re.match(r"\d{4}-\d{2}-\d{2}", cells[0]):
            continue
        out.append(
            {
                "date": cells[0],
                "subs": cells[1],
                "redm": cells[2],
                "shares": cells[3],
                "nav": cells[4],
                "change": cells[5],
            }
        )
    return out


def fetch_fund_gmbd(code: str, timeout: float = 8.0) -> list[dict]:
    """ETF 份额/规模变动（fundf10）。失败返回空列表，由调用方决定要不要显示。"""
    url = (
        "https://fundf10.eastmoney.com/FundArchivesDatas.aspx"
        f"?type=gmbd&code={code.strip()}&rt=0.12"
    )
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://fundf10.eastmoney.com/",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", errors="ignore")
    return parse_fund_gmbd(raw)


def fetch_kline(code: str, kind: str = "股票", count: int = 120, client=None):
    """Daily kline for tech analysis. Returns DataFrame or None."""
    code = code.strip()
    if is_otc_fund(kind, code):
        return None
    market = _market_enum(code)

    def _pull(c):
        return c.get_stock_kline(
            market, code, period=Period.DAILY, count=count, adjust=Adjust.QFQ
        )

    if client is not None:
        kdf = _pull(client)
    else:
        with open_mac_client() as opened:
            kdf = _pull(opened)
    if kdf is None or kdf.empty:
        return None
    return kdf


def to_market_snapshot(quote: dict | None) -> MarketSnapshot | None:
    if not quote:
        return None
    return MarketSnapshot(
        code=quote.get("code") or HS300_CODE,
        name=quote.get("name") or "沪深300",
        price=quote.get("price"),
        day_change_pct=quote.get("day_change_pct"),
        change_20d_pct=quote.get("change_20d_pct"),
        high_120=quote.get("high_120"),
        low_120=quote.get("low_120"),
        error=quote.get("error"),
        daily_returns=list(quote.get("daily_returns") or []),
    )


def to_snapshot(holding: Holding, quote: dict | None) -> PositionSnapshot:
    q = quote or holding.quote or {}
    return PositionSnapshot(
        code=holding.code,
        name=q.get("name") or holding.name or holding.code,
        kind=holding.kind,
        quantity=holding.quantity,
        cost=holding.cost,
        price=q.get("price"),
        high_120=q.get("high_120"),
        low_120=q.get("low_120"),
        announcements=list(q.get("announcements") or []),
        change_20d_pct=q.get("change_20d_pct"),
        daily_returns=list(q.get("daily_returns") or []),
        place=holding.place.strip() or "佣金宝",
        top_holdings=list(q.get("top_holdings") or []),
        holdings_asof=q.get("holdings_asof") or "",
    )
