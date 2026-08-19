"""外部参照：美股半导体链 + 美股期货 + 汇率利率 + A 股设备龙头/行业指数。

数据源是东方财富 push2 批量报价（期货走 futsseapi）；只读，失败就显示暂无，不影响主流程。
"""

from __future__ import annotations

import json
import urllib.request
from datetime import datetime

from holdings.tech import InfoBlock

# (secid, 分组)；名称以接口返回的 f14 为准
WATCHLIST: tuple[tuple[str, str], ...] = (
    ("251.SOX", "总览"),    # 费城半导体指数
    ("100.NDX", "总览"),    # 纳斯达克
    ("105.AMAT", "设备"),   # 应用材料
    ("105.LRCX", "设备"),   # 拉姆研究/泛林
    ("105.KLAC", "设备"),   # 科磊
    ("105.ASML", "设备"),   # 阿斯麦
    ("105.MU", "存储"),     # 美光
    ("105.SNDK", "存储"),   # 闪迪
    ("106.TSM", "制造"),    # 台积电
    ("0.002371", "龙头"),   # 北方华创
    ("1.688012", "龙头"),   # 中微公司
    ("1.688072", "龙头"),   # 拓荆科技
    ("1.688120", "龙头"),   # 华海清科
    ("2.931743", "行业"),   # 中证半导体材料设备主题指数
    ("171.US30Y", "利率"),  # 美国 30 年期国债收益率
    ("171.US10Y", "利率"),  # 美国 10 年期国债收益率
    ("100.UDI", "汇率"),    # 美元指数
    ("133.USDCNH", "汇率"), # 美元兑离岸人民币
)

# 期货走另一个接口（futsseapi），代码格式是下划线连接
FUTURES: tuple[tuple[str, str], ...] = (
    ("103.NQ00Y", "纳指期货"),  # 小型纳指当月连续
    ("103.ES00Y", "标普期货"),  # 小型标普当月连续
)

_GROUP_ORDER = ("总览", "期货", "设备", "存储", "制造", "龙头", "行业", "利率", "汇率")

_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://quote.eastmoney.com/",
}


def _float_or_none(val) -> float | None:
    if val in (None, "-", ""):
        return None
    try:
        v = float(val)
    except (TypeError, ValueError):
        return None
    if v != v:
        return None
    return v


def parse_overseas_payload(raw: dict | None) -> dict[str, dict]:
    """ulist.np/get 的返回 → {secid: {name, price, change_pct, ts}}。纯函数，好测。"""
    data = (raw or {}).get("data") or {}
    rows = data.get("diff") or []
    out: dict[str, dict] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        mkt, code = row.get("f13"), row.get("f12")
        if mkt is None or not code:
            continue
        secid = f"{mkt}.{code}"
        price = _float_or_none(row.get("f2"))
        if price is None:
            continue
        out[secid] = {
            "name": str(row.get("f14") or code),
            "price": price,
            "change_pct": _float_or_none(row.get("f3")),
            "ts": row.get("f124") if isinstance(row.get("f124"), (int, float)) else None,
        }
    return out


def parse_futures_payload(raw: dict | None, name: str) -> dict | None:
    """futsseapi static/{code}_qt 的返回 → 单条 quote。纯函数。"""
    qt = (raw or {}).get("qt")
    if not isinstance(qt, dict):
        return None
    price = _float_or_none(qt.get("p"))
    if price is None:
        return None
    return {
        "name": str(qt.get("name") or name),
        "price": price,
        "change_pct": _float_or_none(qt.get("zdf")),
        "ts": qt.get("spsj") if isinstance(qt.get("spsj"), (int, float)) else None,
    }


def _get_json(url: str, timeout: float) -> dict:
    req = urllib.request.Request(url, headers=_HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def fetch_futures(timeout: float = 8.0) -> dict[str, dict]:
    """美股指数期货，逐个拉，单个失败不影响其他。"""
    out: dict[str, dict] = {}
    for secid, name in FUTURES:
        code = secid.replace(".", "_")
        try:
            raw = _get_json(f"https://futsseapi.eastmoney.com/static/{code}_qt", timeout)
        except Exception:
            continue
        q = parse_futures_payload(raw, name)
        if q:
            out[secid] = q
    return out


def fetch_overseas(timeout: float = 8.0) -> dict[str, dict]:
    secids = ",".join(s for s, _ in WATCHLIST)
    url = (
        "https://push2.eastmoney.com/api/qt/ulist.np/get"
        f"?invt=2&fltt=2&secids={secids}&fields=f12,f13,f14,f2,f3,f124"
    )
    quotes = parse_overseas_payload(_get_json(url, timeout))
    try:
        quotes.update(fetch_futures(timeout=timeout))
    except Exception:
        pass
    return quotes


def _fmt_chg(v: float | None) -> str:
    if v is None:
        return "涨跌暂无"
    return f"{v:+.2f}%"


def _yield_word(chg: float | None) -> str:
    if chg is None or abs(chg) < 0.05:
        return "持平"
    return "上行" if chg > 0 else "回落"


def summarize_overseas(quotes: dict[str, dict] | None) -> InfoBlock:
    if not quotes:
        return InfoBlock(
            title="外部参照暂时没有",
            evidence=["接口连不上或没取到数；不耽误看国内的部分。"],
            ok=False,
        )

    by_group: dict[str, list[str]] = {}
    for secid, group in WATCHLIST:
        q = quotes.get(secid)
        if not q:
            continue
        if group == "利率":
            chg = q.get("change_pct")
            line = f"{q['name']} {q['price']:.4f}%，{_yield_word(chg)}（{_fmt_chg(chg)}）"
        elif group == "汇率":
            line = f"{q['name']} {q['price']:.4f}（{_fmt_chg(q.get('change_pct'))}）"
        else:
            line = f"{q['name']} {_fmt_chg(q.get('change_pct'))}"
        by_group.setdefault(group, []).append(line)
    for secid, _name in FUTURES:
        q = quotes.get(secid)
        if q:
            by_group.setdefault("期货", []).append(f"{q['name']} {_fmt_chg(q.get('change_pct'))}")

    evidence: list[str] = []
    for group in _GROUP_ORDER:
        lines = by_group.get(group)
        if lines:
            evidence.append(f"{group}：" + "、".join(lines))

    # 时间戳只取 push2 来源；期货接口的时间戳时区口径不同，混进来会把数据时间带偏
    ts_list = [
        q["ts"] for secid, _ in WATCHLIST if (q := quotes.get(secid)) and q.get("ts")
    ]
    if ts_list:
        stamp = datetime.fromtimestamp(max(ts_list)).strftime("%m-%d %H:%M")
        evidence.append(
            f"数据时间 {stamp}（北京）。美股夏令时 21:30–次日 04:00 是盘中，"
            "盘前看到的可能是还没走完的数；A 股龙头和行业指数是上个交易日的收盘。"
        )

    sox = quotes.get("251.SOX")
    nq = quotes.get("103.NQ00Y")
    parts: list[str] = []
    if sox:
        parts.append(f"费半 {_fmt_chg(sox.get('change_pct'))}")
    if nq:
        parts.append(f"纳指期货 {_fmt_chg(nq.get('change_pct'))}")
    us30y = quotes.get("171.US30Y")
    if us30y:
        parts.append(f"30 年美债 {us30y['price']:.2f}% {_yield_word(us30y.get('change_pct'))}")
    title = "，".join(parts) if parts else "外部参照"

    if sox and sox.get("change_pct") is not None:
        v = sox["change_pct"]
        if v <= -3:
            evidence.append("费半跌幅不小，明天 A 股半导体竞价多半承压。")
        elif v >= 3:
            evidence.append("费半涨幅不小，明天 A 股半导体情绪有支撑。")
        elif abs(v) < 1:
            evidence.append("费半波动不大，外盘今晚算安静。")
        else:
            evidence.append("费半有波动但幅度一般。")
    if nq and nq.get("change_pct") is not None and abs(nq["change_pct"]) >= 1:
        word = "高" if nq["change_pct"] > 0 else "低"
        evidence.append(
            f"纳指期货波动不小，今晚美股大概率{word}开；"
            "期货是盘前风向，到 A 股开盘还有十几个小时。"
        )
    if quotes.get("133.USDCNH"):
        evidence.append("USDCNH 上行 = 人民币相对走弱，对外资情绪偏空；下行则相反。")
    evidence.append("外盘只影响竞价和情绪；A 股半导体还有自己的高低切换节奏，别拿外盘直接外推全天。")

    return InfoBlock(title=title, evidence=evidence, ok=True)


def attach_overseas(report, *, timeout: float = 8.0):
    """拉取并挂到 TechReport.overseas；失败挂暂无块，绝不打断主流程。"""
    try:
        quotes = fetch_overseas(timeout=timeout)
    except Exception:
        quotes = None
    report.overseas = summarize_overseas(quotes)
    return report
