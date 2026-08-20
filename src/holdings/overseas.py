"""外部参照：通用宏观层（美债/美元/汇率/期货）+ 按持仓行业匹配的行业包。

行业包按名称/板块关键词匹配（pick_pack）；没匹配到就只看宏观层。
数据源是东方财富 push2 批量报价（期货走 futsseapi）；只读，失败就显示暂无，不影响主流程。
"""

from __future__ import annotations

import json
import time
import urllib.request
from datetime import datetime
from pathlib import Path

from holdings.log import get_logger
from holdings.tech import InfoBlock

log = get_logger("overseas")

CACHE_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "cache"
CACHE_TTL = 120.0  # 秒内同一包不重复拉取（连刷不重复打请求，也少触发限流）
CACHE_STALE_OK = 24 * 3600.0  # 兜底缓存超过一天就不用了
RETRY_TIMES = 3  # 首次失败后再试几次
BACKOFF_BASE = 1.5  # 指数退避起点：1.5s、3s、6s

# 通用宏观层：所有持仓都带。(secid, 分组)；名称以接口返回的 f14 为准
COMMON_WATCHLIST: tuple[tuple[str, str], ...] = (
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

# 行业包：keywords 命中名称或板块即启用；watchlist 追加在宏观层之后
PACKS: dict[str, dict] = {
    "半导体": {
        "keywords": ("半导体", "芯片", "集成电路"),
        "watchlist": (
            ("251.SOX", "总览"),   # 费城半导体指数
            ("100.NDX", "总览"),   # 纳斯达克
            ("105.AMAT", "设备"),  # 应用材料
            ("105.LRCX", "设备"),  # 拉姆研究/泛林
            ("105.KLAC", "设备"),  # 科磊
            ("105.ASML", "设备"),  # 阿斯麦
            ("105.MU", "存储"),    # 美光
            ("105.SNDK", "存储"),  # 闪迪
            ("106.TSM", "制造"),   # 台积电
            ("0.002371", "龙头"),  # 北方华创
            ("1.688012", "龙头"),  # 中微公司
            ("1.688072", "龙头"),  # 拓荆科技
            ("1.688120", "龙头"),  # 华海清科
            ("2.931743", "行业"),  # 中证半导体材料设备主题指数
        ),
    },
    "机器人": {
        "keywords": ("机器人",),
        "watchlist": (
            ("105.TSLA", "海外"),  # 特斯拉（人形机器人叙事锚）
            ("105.NVDA", "海外"),  # 英伟达
            ("0.300124", "龙头"),  # 汇川技术
            ("0.002747", "龙头"),  # 埃斯顿
            ("1.688017", "龙头"),  # 绿的谐波
            ("0.002472", "龙头"),  # 双环传动
            ("0.980022", "行业"),  # 国证机器人产业指数
        ),
    },
    "电力设备": {
        "keywords": ("电力设备", "电气", "电力", "风电", "核电", "电源"),
        "watchlist": (
            ("106.GEV", "海外"),   # GE Vernova（发电设备海外锚）
            ("106.ETN", "海外"),   # 伊顿（电网/电力管理）
            ("1.601727", "龙头"),  # 上海电气
            ("1.600875", "龙头"),  # 东方电气
            ("1.600089", "龙头"),  # 特变电工
            ("1.600406", "龙头"),  # 国电南瑞
            ("0.002202", "龙头"),  # 金风科技
            ("0.980148", "行业"),  # 国证电力设备指数
        ),
    },
}

_GROUP_ORDER = ("总览", "海外", "期货", "设备", "存储", "制造", "龙头", "行业", "利率", "汇率")

_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://quote.eastmoney.com/",
}


def pick_pack(name: str = "", boards: list[str] | None = None) -> str | None:
    """按持仓名称/板块关键词选行业包；都没命中返回 None（只看宏观层）。"""
    hay = [name or "", *(boards or [])]
    for pack_name, pack in PACKS.items():
        for kw in pack["keywords"]:
            if any(kw in h for h in hay):
                return pack_name
    return None


def watchlist_for(pack: str | None) -> tuple[tuple[str, str], ...]:
    extra = PACKS.get(pack, {}).get("watchlist", ())
    return COMMON_WATCHLIST + tuple(extra)


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
        except Exception as exc:
            log.info("期货 %s 拉取失败：%s", secid, exc)
            continue
        q = parse_futures_payload(raw, name)
        if q:
            out[secid] = q
    return out


def fetch_overseas(timeout: float = 8.0, pack: str | None = None) -> dict[str, dict]:
    secids = ",".join(s for s, _ in watchlist_for(pack))
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


def _cache_file(pack: str | None) -> Path:
    return CACHE_DIR / f"overseas-{pack or 'macro'}.json"


def _read_cache(pack: str | None) -> tuple[float, dict[str, dict]] | None:
    try:
        raw = json.loads(_cache_file(pack).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict):
        return None
    at, quotes = raw.get("fetched_at"), raw.get("quotes")
    if not isinstance(at, (int, float)) or not isinstance(quotes, dict) or not quotes:
        return None
    return float(at), quotes


def _write_cache(pack: str | None, quotes: dict[str, dict]) -> None:
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        tmp = _cache_file(pack).with_suffix(".tmp")
        tmp.write_text(
            json.dumps({"fetched_at": time.time(), "quotes": quotes}, ensure_ascii=False),
            encoding="utf-8",
        )
        tmp.replace(_cache_file(pack))
    except OSError as exc:
        log.info("外部参照缓存写入失败：%s", exc)


def _try_fetch(pack: str | None, timeout: float) -> dict[str, dict] | None:
    try:
        quotes = fetch_overseas(timeout=timeout, pack=pack)
    except Exception as exc:
        log.info("外部参照拉取异常（包=%s）：%s", pack or "无", exc)
        return None
    if not quotes:
        # 限流的典型表现：没报错但返回空
        log.info("外部参照返回空（包=%s）", pack or "无")
        return None
    return quotes


def fetch_overseas_cached(
    pack: str | None = None,
    timeout: float = 8.0,
    ttl: float = CACHE_TTL,
) -> tuple[dict[str, dict] | None, float, bool]:
    """带避让的拉取。返回 (quotes, 数据时间戳, 是否本次新拉)。

    - TTL 内直接用缓存，不打请求；
    - 失败/为空时指数退避重试 RETRY_TIMES 次（1.5s、3s、6s）；
    - 还失败就回退到 24h 内的旧缓存（fresh=False，由调用方决定是否提示）。
    """
    now = time.time()
    cached = _read_cache(pack)
    if cached and now - cached[0] < ttl:
        return cached[1], cached[0], False

    quotes = _try_fetch(pack, timeout)
    for i in range(RETRY_TIMES):
        if quotes is not None:
            break
        wait = BACKOFF_BASE * (2 ** i)
        log.info("外部参照第 %d 次重试，先等 %.1fs（包=%s）", i + 1, wait, pack or "无")
        time.sleep(wait)
        quotes = _try_fetch(pack, timeout)
    if quotes:
        _write_cache(pack, quotes)
        return quotes, now, True
    if cached and now - cached[0] < CACHE_STALE_OK:
        return cached[1], cached[0], False
    return None, 0.0, False


def _fmt_chg(v: float | None) -> str:
    if v is None:
        return "涨跌暂无"
    return f"{v:+.2f}%"


def _yield_word(chg: float | None) -> str:
    if chg is None or abs(chg) < 0.05:
        return "持平"
    return "上行" if chg > 0 else "回落"


def summarize_overseas(quotes: dict[str, dict] | None, pack: str | None = None) -> InfoBlock:
    if not quotes:
        return InfoBlock(
            title="外部参照暂时没有",
            evidence=["接口连不上或没取到数；不耽误看国内的部分。"],
            ok=False,
        )

    watchlist = watchlist_for(pack)
    by_group: dict[str, list[str]] = {}
    for secid, group in watchlist:
        q = quotes.get(secid)
        if not q:
            continue
        if group == "利率":
            line = f"{q['name']} {q['price']:.4f}%，{_yield_word(q.get('change_pct'))}（{_fmt_chg(q.get('change_pct'))}）"
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
    ts_list = [q["ts"] for secid, _ in watchlist if (q := quotes.get(secid)) and q.get("ts")]
    if ts_list:
        stamp = datetime.fromtimestamp(max(ts_list)).strftime("%m-%d %H:%M")
        evidence.append(
            f"数据时间 {stamp}（北京）。美股夏令时 21:30–次日 04:00 是盘中，"
            "盘前看到的可能是还没走完的数；A 股龙头和行业指数是上个交易日的收盘。"
        )

    parts: list[str] = []
    sox = quotes.get("251.SOX") if any(s == "251.SOX" for s, _ in watchlist) else None
    if sox:
        parts.append(f"费半 {_fmt_chg(sox.get('change_pct'))}")
    nq = quotes.get("103.NQ00Y")
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
    evidence.append("外盘只影响竞价和情绪；A 股还有自己的高低切换节奏，别拿外盘直接外推全天。")

    return InfoBlock(title=title, evidence=evidence, ok=True)


def attach_overseas(
    report,
    *,
    name: str = "",
    boards: list[str] | None = None,
    timeout: float = 8.0,
):
    """按持仓选行业包，拉取并挂到 TechReport.overseas；失败挂暂无块，绝不打断主流程。"""
    pack = pick_pack(name, boards)
    quotes, fetched_at, fresh = fetch_overseas_cached(pack=pack, timeout=timeout)
    if not quotes:
        log.warning("外部参照拉取失败且无缓存兜底（%s，包=%s）", name, pack or "无")
    block = summarize_overseas(quotes, pack=pack)
    if quotes and not fresh and time.time() - fetched_at > CACHE_TTL:
        stamp = datetime.fromtimestamp(fetched_at).strftime("%m-%d %H:%M")
        block.evidence.append(
            f"本次刷新没拉到新数据（可能接口限流），展示的是 {stamp} 拉到的缓存。"
        )
    report.overseas = block
    return report
