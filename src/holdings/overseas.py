"""海外参照：美股半导体链 + 美债收益率，一次批量拉取，给持仓页当背景板。

数据源是东方财富 push2 批量报价；只读，失败就显示暂无，不影响主流程。
"""

from __future__ import annotations

import json
import urllib.request
from datetime import datetime

from holdings.tech import InfoBlock

# (secid, 分组)；名称以接口返回的 f14 为准
WATCHLIST: tuple[tuple[str, str], ...] = (
    ("251.SOX", "总览"),   # 费城半导体指数
    ("100.NDX", "总览"),   # 纳斯达克
    ("105.AMAT", "设备"),  # 应用材料
    ("105.LRCX", "设备"),  # 拉姆研究/泛林
    ("105.KLAC", "设备"),  # 科磊
    ("105.ASML", "设备"),  # 阿斯麦
    ("105.MU", "存储"),    # 美光
    ("105.SNDK", "存储"),  # 闪迪
    ("106.TSM", "制造"),   # 台积电
    ("171.US30Y", "利率"), # 美国 30 年期国债收益率
)

_GROUP_ORDER = ("总览", "设备", "存储", "制造", "利率")


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


def fetch_overseas(timeout: float = 8.0) -> dict[str, dict]:
    secids = ",".join(s for s, _ in WATCHLIST)
    url = (
        "https://push2.eastmoney.com/api/qt/ulist.np/get"
        f"?invt=2&fltt=2&secids={secids}&fields=f12,f13,f14,f2,f3,f124"
    )
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://quote.eastmoney.com/",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = json.loads(resp.read().decode())
    return parse_overseas_payload(raw)


def _fmt_chg(v: float | None) -> str:
    if v is None:
        return "涨跌暂无"
    return f"{v:+.2f}%"


def summarize_overseas(quotes: dict[str, dict] | None) -> InfoBlock:
    if not quotes:
        return InfoBlock(
            title="海外参照暂时没有",
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
            word = "上行" if (chg or 0) > 0 else "回落"
            line = f"{q['name']} {q['price']:.4f}%，{word}（{_fmt_chg(chg)}）"
        else:
            line = f"{q['name']} {_fmt_chg(q.get('change_pct'))}"
        by_group.setdefault(group, []).append(line)

    evidence: list[str] = []
    for group in _GROUP_ORDER:
        lines = by_group.get(group)
        if lines:
            evidence.append(f"{group}：" + "、".join(lines))

    ts_list = [q["ts"] for q in quotes.values() if q.get("ts")]
    if ts_list:
        stamp = datetime.fromtimestamp(max(ts_list)).strftime("%m-%d %H:%M")
        evidence.append(
            f"数据时间 {stamp}（北京）。美股夏令时 21:30–次日 04:00 是盘中，"
            "盘前看到的可能是还没走完的数。"
        )

    sox = quotes.get("251.SOX")
    title = "海外参照"
    if sox:
        title = f"费半 {_fmt_chg(sox.get('change_pct'))}"
        us30y = quotes.get("171.US30Y")
        if us30y:
            chg = us30y.get("change_pct")
            word = "上行" if (chg or 0) > 0 else "回落"
            title += f"，30 年美债 {us30y['price']:.2f}% {word}"
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
