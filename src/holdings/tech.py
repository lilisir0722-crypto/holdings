from __future__ import annotations

import math
from dataclasses import dataclass, field, replace


@dataclass
class TechItem:
    name: str
    reading: str
    evidence: list[str] = field(default_factory=list)
    side: str = "中"  # 多 / 空 / 中
    signal: bool = False
    values: dict[str, float] = field(default_factory=dict)
    about: str = ""


@dataclass
class CapitalBlock:
    title: str
    evidence: list[str] = field(default_factory=list)
    ok: bool = False
    summary_line: str | None = None


@dataclass
class BoardBlock:
    title: str
    evidence: list[str] = field(default_factory=list)
    ok: bool = False
    summary_line: str | None = None


@dataclass
class UnusualBlock:
    title: str
    evidence: list[str] = field(default_factory=list)
    ok: bool = False


@dataclass
class ChanlunBlock:
    title: str
    ok: bool = False
    counts: dict[str, int] = field(default_factory=dict)
    fractals: list[dict] = field(default_factory=list)
    bis: list[dict] = field(default_factory=list)
    zss: list[dict] = field(default_factory=list)
    xds: list[dict] = field(default_factory=list)
    mmds: list[dict] = field(default_factory=list)
    bcs: list[dict] = field(default_factory=list)
    klines: list[dict] = field(default_factory=list)
    note: str = "easy_tdx 按日 K 算出的缠论结论；每条买卖点/背驰带它自己的说明，当作论证来看，不是无依据的一句话。"


@dataclass
class GuideBlock:
    title: str
    evidence: list[str] = field(default_factory=list)


@dataclass
class InfoBlock:
    title: str
    evidence: list[str] = field(default_factory=list)
    ok: bool = False
    summary_line: str | None = None


@dataclass
class TechReport:
    stance: str
    stance_evidence: list[str]
    signals: list[TechItem]
    quiet: list[TechItem]
    trend_title: str = ""
    trend_evidence: list[str] = field(default_factory=list)
    model_note: str | None = None
    model_status: str = "skipped"  # skipped | ok | error
    capital: CapitalBlock | None = None
    boards: list[BoardBlock] = field(default_factory=list)
    unusual: UnusualBlock | None = None
    chanlun: ChanlunBlock | None = None
    guides: list[GuideBlock] = field(default_factory=list)
    timeframes: InfoBlock | None = None
    relative: InfoBlock | None = None
    intraday: InfoBlock | None = None
    xdxr: InfoBlock | None = None
    etf: InfoBlock | None = None


@dataclass
class TrendJudgment:
    title: str
    evidence: list[str] = field(default_factory=list)


# 白话说明：衡量什么 + 常用阈值怎么看（不展开公式）
INDICATOR_ABOUT: dict[str, str] = {
    "MACD": "看短线动能方不方向一致。DIF 上穿 DEA（金叉）或柱由负转正，常说偏强；死叉或柱转负，常说偏弱。",
    "KDJ": "看最近一段涨跌里价格处在偏强还是偏弱。K、D 一般看 0–100；K 大于约 80 常说超买偏热，小于约 20 常说超卖偏冷；J 更灵敏，大于约 100 或小于约 0 也常作参考。",
    "RSI": "看一段时间内涨跌力量谁占上风。常见看 0–100；大于约 70 常说偏热（超买），小于约 30 常说偏冷（超卖）。",
    "布林": "看价格相对近期波动区间的位置。碰到或突破上轨常说偏热，碰到或跌破下轨常说偏冷；在中轨附近多说中性。",
    "CCI": "看价格是否偏离近期常态。大于约 +100 常说偏热，小于约 −100 常说偏冷。",
    "WR": "威廉指标，看收盘价在最近高低区间里偏上还是偏下。0–100 取值：小于约 20（收在区间顶部）常说偏热超买；大于约 80（收在区间底部）常说偏冷超卖。",
    "均线": "看现价和短、中期平均成本的关系。价格与短均线都在长均线上方，常说偏多头；都在下方，常说偏空头。",
    "ATR": "看近期波动有多大，数值本身不直接说涨跌方向。",
    "BIAS": "看现价偏离均线有多远。偏离过大常提示涨跌已经走得比较急。",
    "PSY": "看一段日子里上涨天数占比，偏高常说情绪偏热，偏低常说偏冷。",
    "OBV": "结合成交量看资金是否在跟涨或跟跌。近几日价格涨、能量潮却掉，或价格跌、能量潮却升，常说量价背离。",
    "MFI": "资金流量，0–100。大于约 80 常说偏热，小于约 20 常说偏冷。",
    "DMI": "看趋势是否明确、多空谁占优。+DI 上穿 −DI 常说偏多；ADX 大约高于 25 常说趋势在加强。",
    "VR": "容量比率，看涨日成交相对跌日成交。数值很高常说偏热，很低常说偏冷。",
    "SAR": "抛物线止损位，价格在 SAR 上方常说偏多，下方常说偏空。",
    "VWAP": "成交量加权均价，常当作近期机构成本参考；现价在上方或下方只作位置参考。",
    "AROON": "看新高、新低出现得是否频繁，用来观察趋势是否刚启动或在减弱。",
}


def _about(name: str) -> str:
    return INDICATOR_ABOUT.get(name, f"{name}：用近期行情算出的参考数，阈值因指标而异。")


def _fmt_money(x: float) -> str:
    if not math.isfinite(x):
        x = 0.0
    ax = abs(x)
    if ax >= 1e8:
        return f"{x / 1e8:.2f} 亿"
    if ax >= 1e4:
        return f"{x / 1e4:.0f} 万"
    return f"{x:.0f} 元"


def _is_missing(val) -> bool:
    if val is None:
        return True
    try:
        import pandas as pd

        return bool(pd.isna(val))
    except (TypeError, ValueError):
        return False


def _finite_float(val, *, default: float | None = 0.0) -> float | None:
    if _is_missing(val):
        return default
    try:
        v = float(val)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(v):
        return None
    return v


def summarize_capital(df) -> CapitalBlock:
    """Summarize latest capital flow row from easy-tdx capital DataFrame."""
    empty = CapitalBlock(title="这只暂时没有资金流向", ok=False)
    if df is None or getattr(df, "empty", True):
        return empty
    if "date" not in df.columns:
        return empty
    ordered = df.sort_values("date")
    last = ordered.iloc[-1]
    raw_date = last["date"]
    if _is_missing(raw_date):
        return empty
    date_str = str(raw_date)[:10]
    if date_str.lower() in ("", "nan", "nat", "none"):
        return empty

    if "main_net" in ordered.columns:
        main_net = _finite_float(last["main_net"], default=None)
        if main_net is None:
            return CapitalBlock(title="主力净流入数据不可用", ok=False)
    else:
        main_net = 0.0

    if "small_net" in ordered.columns:
        small_net = _finite_float(last["small_net"], default=0.0)
        if small_net is None:
            small_net = 0.0
    else:
        small_net = 0.0

    main_fmt = _fmt_money(main_net)
    small_fmt = _fmt_money(small_net)
    direction = "为正" if main_net >= 0 else "为负"
    summary_line = f"最近一日主力净流入{direction}"
    title = f"主力净流入 {main_fmt}"
    evidence = [
        f"{date_str} 主力净流入 {main_fmt}",
        f"散户（小单）净流入 {small_fmt}",
    ]
    return CapitalBlock(
        title=title,
        evidence=evidence,
        ok=True,
        summary_line=summary_line,
    )


# easy-tdx BoardType: HY=0, HY2=1; belong lists sometimes use 2 for industry; GN=3
_INDUSTRY_BOARD_TYPES = {0, 1, 2}
_CONCEPT_BOARD_TYPES = {3}


def _normalize_board_summaries(summaries) -> dict:
    if summaries is None:
        return {}
    if isinstance(summaries, dict):
        return summaries
    out: dict = {}
    for item in summaries:
        if not isinstance(item, dict):
            continue
        code = item.get("board_code") or item.get("code")
        if code is None:
            continue
        out[str(code)] = item
    return out


def _board_type_bucket(board_type, board_name: str) -> int:
    """0=industry, 1=concept, 2=other/fallback."""
    if board_type is not None and not _is_missing(board_type):
        if isinstance(board_type, str):
            s = board_type.strip()
            upper = s.upper()
            if "行业" in s or upper in ("HY", "HY2", "0", "1", "2"):
                return 0
            if "概念" in s or upper in ("GN", "3"):
                return 1
            try:
                board_type = int(float(s))
            except (TypeError, ValueError):
                board_type = None
        if isinstance(board_type, (int, float)) and not isinstance(board_type, bool):
            iv = int(board_type)
            if iv in _INDUSTRY_BOARD_TYPES:
                return 0
            if iv in _CONCEPT_BOARD_TYPES:
                return 1
    # board_type unclear → name heuristics
    if "行业" in board_name:
        return 0
    if "概念" in board_name:
        return 1
    return 2


def select_belong_boards(belong_df, limit: int = 2) -> list[dict]:
    """Pick up to ``limit`` belong-board rows: industry, then concept, else first rows."""
    if belong_df is None or getattr(belong_df, "empty", True):
        return []
    rows: list[tuple[int, int, dict]] = []
    for idx, raw in enumerate(belong_df.to_dict(orient="records")):
        code = raw.get("board_code")
        if code is None or _is_missing(code):
            code = raw.get("code")
        if code is None or _is_missing(code):
            continue
        name = raw.get("board_name")
        if name is None or _is_missing(name):
            name = raw.get("name") or ""
        name_s = str(name)
        code_s = str(code).strip()
        if not code_s:
            continue
        bucket = _board_type_bucket(raw.get("board_type"), name_s)
        rows.append(
            (
                bucket,
                idx,
                {
                    "board_code": code_s,
                    "board_name": name_s or code_s,
                    "board_type": raw.get("board_type"),
                },
            )
        )
    rows.sort(key=lambda t: (t[0], t[1]))
    return [r[2] for r in rows[: max(0, limit)]]


def pick_boards(belong_df, summaries: dict | list | None = None, limit: int = 2) -> list[BoardBlock]:
    """Build BoardBlock list from belong DF + get_board_summary scalars (no members)."""
    empty = BoardBlock(title="板块对不上 / 暂无", ok=False)
    selected = select_belong_boards(belong_df, limit=limit)
    if not selected:
        return [empty]

    by_code = _normalize_board_summaries(summaries)
    blocks: list[BoardBlock] = []
    for row in selected:
        code = row["board_code"]
        name = row["board_name"]
        summary = by_code.get(code)
        if not summary or summary.get("error"):
            blocks.append(
                BoardBlock(
                    title=f"{name}：板块暂无",
                    evidence=["板块汇总暂时拿不到"],
                    ok=False,
                )
            )
            continue

        main = _finite_float(summary.get("main_net_amount"), default=0.0) or 0.0
        main_3d = _finite_float(summary.get("main_net_3d"), default=None)
        main_5d = _finite_float(summary.get("main_net_5d"), default=None)
        amount = _finite_float(summary.get("amount"), default=None)
        members = summary.get("member_count")
        up_c = summary.get("up_count")
        down_c = summary.get("down_count")

        main_fmt = _fmt_money(main)
        direction = "为正" if main >= 0 else "为负"
        evidence = [f"主力净流入 {main_fmt}"]
        if main_3d is not None:
            evidence.append(f"近 3 日主力净流入 {_fmt_money(main_3d)}")
        if main_5d is not None:
            evidence.append(f"近 5 日主力净流入 {_fmt_money(main_5d)}")
        if amount is not None:
            evidence.append(f"成交额 {_fmt_money(amount)}")
        if members is not None and not _is_missing(members):
            try:
                evidence.append(f"成分股 {int(members)} 只")
            except (TypeError, ValueError):
                pass
        if (
            up_c is not None
            and down_c is not None
            and not _is_missing(up_c)
            and not _is_missing(down_c)
        ):
            try:
                evidence.append(f"涨 {int(up_c)} / 跌 {int(down_c)}")
            except (TypeError, ValueError):
                pass

        blocks.append(
            BoardBlock(
                title=f"{name}（{code}）",
                evidence=evidence,
                ok=True,
                summary_line=f"所属板块 {name} 主力净流入{direction}",
            )
        )
    return blocks or [empty]


EMPTY_MARKET_CTX = {
    "capital_df": None,
    "belong_df": None,
    "board_summaries": {},
    "unusual_df": None,
    "weekly_df": None,
    "min60_df": None,
    "hs300_df": None,
    "board_klines": {},
    "board_rank_1d": None,
    "board_rank_20d": None,
    "tick_df": None,
    "auction_df": None,
    "xdxr_df": None,
    "etf": None,
}


def _code6(value) -> str:
    s = str(value).strip()
    if s.endswith(".0"):
        s = s[:-2]
    digits = "".join(ch for ch in s if ch.isdigit())
    if not digits:
        return s
    return digits.zfill(6)[-6:]


def summarize_unusual(df, code: str) -> UnusualBlock:
    """Filter easy-tdx market unusual list down to this code."""
    empty = UnusualBlock(title="今天没出现在异动名单", ok=False)
    if df is None or getattr(df, "empty", True):
        return empty
    want = _code6(code)
    if not want:
        return empty
    hits: list[str] = []
    for raw in df.to_dict(orient="records"):
        row_code = raw.get("code")
        if row_code is None or _is_missing(row_code):
            continue
        if _code6(row_code) != want:
            continue
        desc = raw.get("desc") or raw.get("description") or ""
        value = raw.get("value")
        when = raw.get("time")
        name = raw.get("name") or ""
        parts = [str(x) for x in (when, name, desc, value) if x is not None and str(x).strip() and not _is_missing(x)]
        hits.append(" ".join(parts) if parts else str(raw))
    if not hits:
        return empty
    return UnusualBlock(
        title=f"异动名单里有这只，共 {len(hits)} 条",
        evidence=hits,
        ok=True,
    )


def _fmt_day(dt) -> str:
    if dt is None or _is_missing(dt):
        return ""
    if hasattr(dt, "strftime"):
        try:
            return dt.strftime("%Y-%m-%d")
        except (TypeError, ValueError):
            pass
    return str(dt)[:10]


def klines_from_dataframe(df) -> list[dict]:
    """Daily OHLC for the chanlun chart. Dates as YYYY-MM-DD to match ChanlunResult."""
    if df is None or getattr(df, "empty", True):
        return []
    rows: list[dict] = []
    for raw in df.to_dict(orient="records"):
        dt = raw.get("datetime")
        if dt is None or _is_missing(dt):
            dt = raw.get("date")
        date_s = _fmt_day(dt)
        o = _finite_float(raw.get("open"), default=None)
        h = _finite_float(raw.get("high"), default=None)
        low = _finite_float(raw.get("low"), default=None)
        c = _finite_float(raw.get("close"), default=None)
        if not date_s or None in (o, h, low, c):
            continue
        rows.append(
            {
                "date": date_s,
                "open": o,
                "high": h,
                "low": low,
                "close": c,
            }
        )
    return rows


def chanlun_from_dict(data: dict | None) -> ChanlunBlock:
    """Turn easy_tdx ChanlunResult.to_dict() (+ optional fractals) into a page block."""
    if not data:
        return ChanlunBlock(title="缠论这次没有结果", ok=False)
    counts = {
        "原始K线": int(data.get("kline_count") or 0),
        "缠论K线": int(data.get("ckline_count") or 0),
        "分型": int(data.get("fractal_count") or len(data.get("fractals") or [])),
        "笔": int(data.get("bi_count") or len(data.get("bis") or [])),
        "中枢": int(data.get("zs_count") or len(data.get("zss") or [])),
        "线段": int(data.get("xd_count") or len(data.get("xds") or [])),
        "买卖点": int(data.get("mmd_count") or len(data.get("mmds") or [])),
        "背驰": int(data.get("bc_count") or len(data.get("bcs") or [])),
    }
    return ChanlunBlock(
        title="缠论（easy_tdx 日线）",
        ok=True,
        counts=counts,
        fractals=list(data.get("fractals") or []),
        bis=list(data.get("bis") or []),
        zss=list(data.get("zss") or []),
        xds=list(data.get("xds") or []),
        mmds=list(data.get("mmds") or []),
        bcs=list(data.get("bcs") or []),
        klines=list(data.get("klines") or []),
    )


def analyze_chanlun(df, code: str = "") -> ChanlunBlock:
    """Run easy_tdx ChanlunAnalyser on daily kline. Does not invent extra fields."""
    if df is None or getattr(df, "empty", True):
        return ChanlunBlock(title="没有日 K，缠论算不了", ok=False)
    try:
        from easy_tdx.chanlun import ChanlunAnalyser

        analyser = ChanlunAnalyser(code or "", "DAILY")
        result = analyser.process_klines(df)
        data = result.to_dict()
        fractals: list[dict] = []
        for fx in result.fractals:
            date_s = None
            try:
                date_s = result._fmt_dt(fx.k.date) if fx.k else None
            except Exception:
                date_s = None
            fractals.append(
                {
                    "index": fx.index,
                    "type": getattr(fx.fx_type, "value", str(fx.fx_type)),
                    "val": round(float(fx.val), 4),
                    "date": date_s,
                    "done": bool(fx.done),
                }
            )
        data["fractals"] = fractals
        data["fractal_count"] = len(fractals)
        data["klines"] = klines_from_dataframe(df)
        return chanlun_from_dict(data)
    except Exception as exc:
        return ChanlunBlock(title=f"缠论这次没算出来：{exc}", ok=False)


def attach_market_context(
    report: TechReport, ctx: dict | None, *, code: str = ""
) -> TechReport:
    """Attach capital/boards/unusual even when ctx is missing, so the page still shows 暂无."""
    data = ctx or EMPTY_MARKET_CTX
    report.capital = summarize_capital(data.get("capital_df"))
    report.boards = pick_boards(data.get("belong_df"), data.get("board_summaries") or {})
    report.unusual = summarize_unusual(data.get("unusual_df"), code)
    for line in [report.capital.summary_line if report.capital else None] + [
        b.summary_line for b in report.boards
    ]:
        if line:
            report.stance_evidence.append(line)
    return report


def _item(
    name: str,
    reading: str,
    *,
    evidence: list[str] | None = None,
    side: str = "中",
    signal: bool = False,
    values: dict[str, float] | None = None,
) -> TechItem:
    return TechItem(
        name=name,
        reading=reading,
        evidence=list(evidence or []),
        side=side,
        signal=signal,
        values=dict(values or {}),
        about=_about(name),
    )


def _last(xs: list[float] | None, n: int = 1) -> float | None:
    if not xs or len(xs) < n:
        return None
    return float(xs[-n])


def _cross_up(a: list[float], b: list[float]) -> bool:
    if len(a) < 2 or len(b) < 2:
        return False
    return a[-2] <= b[-2] and a[-1] > b[-1]


def _cross_down(a: list[float], b: list[float]) -> bool:
    if len(a) < 2 or len(b) < 2:
        return False
    return a[-2] >= b[-2] and a[-1] < b[-1]


def _flip_pos(hist: list[float]) -> bool:
    if len(hist) < 2:
        return False
    return hist[-2] <= 0 < hist[-1]


def _flip_neg(hist: list[float]) -> bool:
    if len(hist) < 2:
        return False
    return hist[-2] >= 0 > hist[-1]


def _item_macd(series: dict) -> TechItem | None:
    dif = series.get("MACD_DIF")
    dea = series.get("MACD_DEA")
    hist = series.get("MACD_HIST")
    if not dif or not dea or not hist:
        return None
    values = {
        "DIF": float(dif[-1]),
        "DEA": float(dea[-1]),
        "柱": float(hist[-1]),
    }
    evidence = [f"DIF {values['DIF']:.4f}，DEA {values['DEA']:.4f}，柱 {values['柱']:.4f}"]
    if _cross_up(dif, dea) or _flip_pos(hist):
        return TechItem(
            name="MACD",
            reading="MACD 出现金叉或柱转正，短线偏强",
            evidence=evidence,
            side="多",
            signal=True,
            values=values,
        )
    if _cross_down(dif, dea) or _flip_neg(hist):
        return TechItem(
            name="MACD",
            reading="MACD 出现死叉或柱转负，短线偏弱",
            evidence=evidence,
            side="空",
            signal=True,
            values=values,
        )
    reading = "MACD 没有明显交叉"
    if hist[-1] > 0:
        reading = "MACD 柱在零轴上方，偏强但没有新交叉"
    elif hist[-1] < 0:
        reading = "MACD 柱在零轴下方，偏弱但没有新交叉"
    if len(hist) >= 2 and abs(float(hist[-1])) < abs(float(hist[-2])):
        reading += "；柱较上日收窄，动能在减弱"
    return TechItem(
        name="MACD",
        reading=reading,
        evidence=evidence,
        side="中",
        signal=False,
        values=values,
    )


def _item_kdj(series: dict) -> TechItem | None:
    k = series.get("KDJ_K")
    d = series.get("KDJ_D")
    j = series.get("KDJ_J")
    if not k or not d:
        return None
    values = {"K": float(k[-1]), "D": float(d[-1])}
    if j:
        values["J"] = float(j[-1])
    evidence = [f"K {values['K']:.1f}，D {values['D']:.1f}" + (f"，J {values['J']:.1f}" if "J" in values else "")]
    if _cross_up(k, d) and k[-1] < 80:
        return TechItem(
            name="KDJ",
            reading="KDJ 金叉，短线偏强",
            evidence=evidence,
            side="多",
            signal=True,
            values=values,
        )
    if _cross_down(k, d) and k[-1] > 20:
        return TechItem(
            name="KDJ",
            reading="KDJ 死叉，短线偏弱",
            evidence=evidence,
            side="空",
            signal=True,
            values=values,
        )
    if k[-1] >= 80 or (j and j[-1] >= 100):
        return TechItem(
            name="KDJ",
            reading="KDJ 进入超买区，偏热",
            evidence=evidence,
            side="空",
            signal=True,
            values=values,
        )
    if k[-1] <= 20 or (j and j[-1] <= 0):
        return TechItem(
            name="KDJ",
            reading="KDJ 进入超卖区，偏冷",
            evidence=evidence,
            side="多",
            signal=True,
            values=values,
        )
    return TechItem(
        name="KDJ",
        reading="KDJ 在中间地带，没有明显信号",
        evidence=evidence,
        side="中",
        signal=False,
        values=values,
    )


def _item_rsi(series: dict) -> TechItem | None:
    rsi = series.get("RSI")
    if not rsi:
        return None
    v = float(rsi[-1])
    values = {"RSI": v}
    evidence = [f"RSI {v:.1f}"]
    if v >= 70:
        return TechItem(
            name="RSI",
            reading="RSI 偏热（超买区）",
            evidence=evidence,
            side="空",
            signal=True,
            values=values,
        )
    if v <= 30:
        return TechItem(
            name="RSI",
            reading="RSI 偏冷（超卖区）",
            evidence=evidence,
            side="多",
            signal=True,
            values=values,
        )
    return TechItem(
        name="RSI",
        reading="RSI 在中间，没有明显过热或过冷",
        evidence=evidence,
        side="中",
        signal=False,
        values=values,
    )


def _item_boll(series: dict) -> TechItem | None:
    up = series.get("BOLL_UPPER")
    mid = series.get("BOLL_MID")
    low = series.get("BOLL_LOWER")
    close = series.get("close")
    if not up or not mid or not low or not close:
        return None
    c, u, m, l = float(close[-1]), float(up[-1]), float(mid[-1]), float(low[-1])
    values = {"收盘": c, "上轨": u, "中轨": m, "下轨": l}
    evidence = [f"收盘 {c:.4f}，上轨 {u:.4f}，中轨 {m:.4f}，下轨 {l:.4f}"]
    span = u - l
    if span <= 0:
        return TechItem(
            name="布林",
            reading="布林带宽度异常，暂不解读",
            evidence=evidence,
            side="中",
            signal=False,
            values=values,
        )
    if c >= u:
        return TechItem(
            name="布林",
            reading="价格碰到或突破布林上轨，偏热",
            evidence=evidence,
            side="空",
            signal=True,
            values=values,
        )
    if c <= l:
        return TechItem(
            name="布林",
            reading="价格碰到或跌破布林下轨，偏冷",
            evidence=evidence,
            side="多",
            signal=True,
            values=values,
        )
    place = (c - l) / span
    return TechItem(
        name="布林",
        reading=f"价格在布林带内，大约在 {place:.0%} 的位置",
        evidence=evidence,
        side="中",
        signal=False,
        values=values,
    )


def _item_cci(series: dict) -> TechItem | None:
    cci = series.get("CCI")
    if not cci:
        return None
    v = float(cci[-1])
    values = {"CCI": v}
    evidence = [f"CCI {v:.1f}"]
    if v >= 100:
        return TechItem(
            name="CCI",
            reading="CCI 偏热",
            evidence=evidence,
            side="空",
            signal=True,
            values=values,
        )
    if v <= -100:
        return TechItem(
            name="CCI",
            reading="CCI 偏冷",
            evidence=evidence,
            side="多",
            signal=True,
            values=values,
        )
    return TechItem(
        name="CCI",
        reading="CCI 在中间",
        evidence=evidence,
        side="中",
        signal=False,
        values=values,
    )


def _item_wr(series: dict) -> TechItem | None:
    wr = series.get("WR1") or series.get("WR")
    if not wr:
        return None
    v = float(wr[-1])
    values = {"WR": v}
    evidence = [f"WR {v:.1f}"]
    # easy_tdx WR 取值 0~100：靠近 0 是收在区间顶部（超买偏热），靠近 100 是收在区间底部（超卖偏冷）
    if v <= 20:
        return TechItem(
            name="WR",
            reading="威廉指标偏热",
            evidence=evidence,
            side="空",
            signal=True,
            values=values,
        )
    if v >= 80:
        return TechItem(
            name="WR",
            reading="威廉指标偏冷",
            evidence=evidence,
            side="多",
            signal=True,
            values=values,
        )
    return TechItem(
        name="WR",
        reading="威廉指标在中间",
        evidence=evidence,
        side="中",
        signal=False,
        values=values,
    )


def _item_ma(series: dict) -> TechItem | None:
    close = series.get("close")
    ma5 = series.get("MA5")
    ma10 = series.get("MA10")
    ma20 = series.get("MA20")
    if not close or not ma5 or not ma20:
        return None
    c, a5, a20 = float(close[-1]), float(ma5[-1]), float(ma20[-1])
    values = {"收盘": c, "MA5": a5, "MA20": a20}
    evidence = [f"收盘 {c:.4f}，MA5 {a5:.4f}，MA20 {a20:.4f}"]
    if ma10:
        values["MA10"] = float(ma10[-1])
        evidence[0] += f"，MA10 {values['MA10']:.4f}"
    if c > a5 > a20:
        return TechItem(
            name="均线",
            reading="短均线在长均线上方，价格也站上，偏多头排列",
            evidence=evidence,
            side="多",
            signal=True,
            values=values,
        )
    if c < a5 < a20:
        return TechItem(
            name="均线",
            reading="短均线在长均线下方，价格也跌破，偏空头排列",
            evidence=evidence,
            side="空",
            signal=True,
            values=values,
        )
    return TechItem(
        name="均线",
        reading="均线没有整齐的多头或空头排列",
        evidence=evidence,
        side="中",
        signal=False,
        values=values,
    )


def _item_obv(series: dict) -> TechItem | None:
    close = series.get("close")
    obv = series.get("OBV")
    if not obv:
        return None
    last = float(obv[-1])
    values = {"OBV": last}
    evidence = [f"OBV {last:.4f}"]
    if not close or len(close) < 6 or len(obv) < 6:
        return _item(
            "OBV",
            "OBV 天数不够，看不出和价格是否背离",
            evidence=evidence,
            values=values,
        )
    d_close = float(close[-1]) - float(close[-6])
    d_obv = float(obv[-1]) - float(obv[-6])
    evidence.append(f"近 5 日价格变化 {d_close:.4f}，OBV 变化 {d_obv:.4f}")
    if d_close > 0 and d_obv < 0:
        return _item(
            "OBV",
            "价格上涨但 OBV 走低，量价背离",
            evidence=evidence,
            side="空",
            signal=True,
            values=values,
        )
    if d_close < 0 and d_obv > 0:
        if len(close) >= 2 and len(obv) >= 2 and float(close[-2]):
            day_chg = float(close[-1]) / float(close[-2]) - 1
            day_obv = float(obv[-1]) - float(obv[-2])
            if day_chg <= -0.03 and day_obv < 0:
                evidence.append("最近一日大跌且 OBV 当日回落，5 日背离多来自前几日，强度打折")
        return _item(
            "OBV",
            "价格下跌但 OBV 走高，量价背离",
            evidence=evidence,
            side="多",
            signal=True,
            values=values,
        )
    return _item(
        "OBV",
        "OBV 与价格大致同向，没有明显背离",
        evidence=evidence,
        values=values,
    )


def _item_mfi(series: dict) -> TechItem | None:
    mfi = series.get("MFI")
    if not mfi:
        return None
    last = float(mfi[-1])
    values = {"MFI": last}
    evidence = [f"MFI {last:.2f}"]
    if last > 80:
        return _item(
            "MFI",
            "资金流量偏热（超买）",
            evidence=evidence,
            side="空",
            signal=True,
            values=values,
        )
    if last < 20:
        return _item(
            "MFI",
            "资金流量偏冷（超卖）",
            evidence=evidence,
            side="多",
            signal=True,
            values=values,
        )
    return _item(
        "MFI",
        "资金流量在中间",
        evidence=evidence,
        values=values,
    )


def _item_dmi(series: dict) -> TechItem | None:
    pdi = series.get("DMI_PDI")
    mdi = series.get("DMI_MDI")
    adx = series.get("DMI_ADX")
    if not pdi or not mdi:
        return None
    p, m = float(pdi[-1]), float(mdi[-1])
    values = {"PDI": p, "MDI": m}
    evidence = [f"+DI {p:.2f}，−DI {m:.2f}"]
    adx_last = float(adx[-1]) if adx else None
    if adx_last is not None:
        values["ADX"] = adx_last
        evidence.append(f"ADX {adx_last:.2f}")
    if _cross_up(pdi, mdi):
        return _item(
            "DMI",
            "+DI 上穿 −DI，偏多",
            evidence=evidence,
            side="多",
            signal=True,
            values=values,
        )
    if _cross_down(pdi, mdi):
        return _item(
            "DMI",
            "+DI 下穿 −DI，偏空",
            evidence=evidence,
            side="空",
            signal=True,
            values=values,
        )
    if adx_last is not None and adx_last >= 25:
        if p > m:
            return _item(
                "DMI",
                "ADX 偏高且 +DI 占优，趋势偏多",
                evidence=evidence,
                side="多",
                signal=True,
                values=values,
            )
        if m > p:
            return _item(
                "DMI",
                "ADX 偏高且 −DI 占优，趋势偏空",
                evidence=evidence,
                side="空",
                signal=True,
                values=values,
            )
    return _item(
        "DMI",
        "动向指标没有明确交叉或强趋势",
        evidence=evidence,
        values=values,
    )


def _item_vr(series: dict) -> TechItem | None:
    vr = series.get("VR")
    if not vr:
        return None
    last = float(vr[-1])
    values = {"VR": last}
    evidence = [f"VR {last:.2f}"]
    if last > 450:
        return _item(
            "VR",
            "容量比率偏高，偏热",
            evidence=evidence,
            side="空",
            signal=True,
            values=values,
        )
    if last < 40:
        return _item(
            "VR",
            "容量比率偏低，偏冷",
            evidence=evidence,
            side="多",
            signal=True,
            values=values,
        )
    return _item(
        "VR",
        "容量比率在中间",
        evidence=evidence,
        values=values,
    )


_HANDLERS = (
    _item_macd,
    _item_kdj,
    _item_rsi,
    _item_boll,
    _item_cci,
    _item_wr,
    _item_ma,
    _item_obv,
    _item_mfi,
    _item_dmi,
    _item_vr,
)

# Remaining indicator column prefixes → display name
_QUIET_MAP = {
    "ATR": "ATR",
    "BIAS": "BIAS",
    "PSY": "PSY",
    "TRIX": "TRIX",
    "DPO": "DPO",
    "MTM": "MTM",
    "ROC": "ROC",
    "EXPMA": "EXPMA",
    "BBI": "BBI",
    "DFMA": "DFMA",
    "CR": "CR",
    "KTN": "KTN",
    "XSII": "XSII",
    "EMV": "EMV",
    "MASS": "MASS",
    "AR": "BRAR",
    "BR": "BRAR",
    "ASI": "ASI",
    "ZY_": "捉妖",
    "BS_": "BIAS信号",
    "TAQ": "唐安奇",
    "SAR": "SAR",
    "VWAP": "VWAP",
    "AROON": "AROON",
    "FK": "FK",
}


def _quiet_from_series(series: dict, taken: set[str]) -> list[TechItem]:
    items: list[TechItem] = []
    seen: set[str] = set()
    for key, vals in series.items():
        if key in ("close", "open", "high", "low", "vol", "amount"):
            continue
        # 只排除 MA5/MA20 这类均线列；MASS 等指标列不能误杀
        if key.startswith("MA") and key[2:].isdigit():
            continue
        if key.startswith(("MACD_", "KDJ_", "BOLL_", "RSI", "CCI", "WR")):
            continue
        label = None
        for prefix, name in _QUIET_MAP.items():
            if key == prefix or key.startswith(prefix):
                label = name
                break
        if not label or label in taken or label in seen:
            continue
        if not vals:
            continue
        seen.add(label)
        v = float(vals[-1])
        items.append(
            TechItem(
                name=label,
                reading=f"{label} 最新值 {v:.4f}，没有触发常用阈值",
                evidence=[f"{key}={v:.4f}"],
                side="中",
                signal=False,
                values={key: v},
            )
        )
    return items


def _stance(signals: list[TechItem]) -> tuple[str, list[str]]:
    bull = [s for s in signals if s.side == "多"]
    bear = [s for s in signals if s.side == "空"]
    evidence: list[str] = []
    for s in signals:
        evidence.append(f"{s.name}：{s.reading}")
    if bull and bear:
        return "指标说法不一致，更宜观望。", evidence
    if len(bull) >= 2 and not bear:
        return "偏多信号更多，更宜谨慎加仓。", evidence
    if len(bear) >= 2 and not bull:
        return "偏空信号更多，更宜先减一点。", evidence
    if len(bull) == 1 and not bear:
        return "只有少量偏多信号，更宜观望或小步试。", evidence
    if len(bear) == 1 and not bull:
        return "只有少量偏空信号，更宜观望。", evidence
    return "没有特别强的技术信号，更宜观望。", evidence or ["没有触发常用阈值的指标"]


def judge_trend(series: dict[str, list[float]]) -> TrendJudgment:
    """Rule-based short-term trend from closes / MAs."""
    close = series.get("close") or []
    if len(close) < 21:
        return TrendJudgment(
            title="走势暂时算不清。",
            evidence=["日 K 不够约 20 个交易日"],
        )
    last = float(close[-1])
    old = float(close[-21])
    change_20 = last / old - 1 if old else 0.0
    prev = float(close[-2])
    change_1 = last / prev - 1 if prev else 0.0
    ma5 = series.get("MA5")
    ma20 = series.get("MA20")
    if not ma20 or len(ma20) < 1:
        # compute simple MA20 from closes
        window = close[-20:]
        ma20_last = sum(window) / len(window)
    else:
        ma20_last = float(ma20[-1])
    ma5_last = float(ma5[-1]) if ma5 and len(ma5) >= 1 else None

    evidence = [
        f"最近约 20 个交易日{( '涨' if change_20 >= 0 else '跌' )}了 {abs(change_20):.1%}",
        f"最近一根 K 线{( '涨' if change_1 >= 0 else '跌' )}了 {abs(change_1):.1%}",
        f"现价 {last:.4f}，相对 MA20 {ma20_last:.4f} 在{'上方' if last >= ma20_last else '下方'}",
    ]
    if ma5_last is not None:
        if ma5_last > ma20_last * 1.002:
            evidence.append(f"MA5 {ma5_last:.4f} 在 MA20 上方")
            ma_side = "多"
        elif ma5_last < ma20_last * 0.998:
            evidence.append(f"MA5 {ma5_last:.4f} 在 MA20 下方")
            ma_side = "空"
        else:
            evidence.append(f"MA5 {ma5_last:.4f} 与 MA20 纠缠")
            ma_side = "中"
    else:
        ma_side = "中"

    above = last >= ma20_last
    score = 0
    if change_20 >= 0.03:
        score += 1
    elif change_20 <= -0.03:
        score -= 1
    if change_1 >= 0.03:
        score += 1
    elif change_1 <= -0.03:
        score -= 1
    if above:
        score += 1
    else:
        score -= 1
    if ma_side == "多":
        score += 1
    elif ma_side == "空":
        score -= 1
    if ma5_last is not None:
        score += 1 if last > ma5_last else -1

    if score >= 2:
        title = "短线偏强。"
    elif score <= -2:
        title = "短线偏弱。"
    else:
        title = "短线震荡。"
    evidence.append("这是规则根据涨跌和均线拼的，不是对后面盈亏的保证。")
    return TrendJudgment(title=title, evidence=evidence)


def _pct_change(close: list[float], days: int) -> float | None:
    if len(close) < days + 1:
        return None
    old = float(close[-(days + 1)])
    last = float(close[-1])
    if not old:
        return None
    return last / old - 1


def _max_drawdown(close: list[float]) -> float:
    peak = float(close[0])
    worst = 0.0
    for c in close:
        v = float(c)
        if v > peak:
            peak = v
        if peak:
            dd = 1.0 - v / peak
            if dd > worst:
                worst = dd
    return worst


def build_guides(series: dict[str, list[float]], trend: TrendJudgment) -> list[GuideBlock]:
    """1–4 条对照：行情类型、量价、这段好不好拿、近强从哪来。"""
    close = [float(x) for x in (series.get("close") or [])]
    guides: list[GuideBlock] = []

    adx = series.get("DMI_ADX")
    adx_last = float(adx[-1]) if adx else None
    how = "指标偏热/偏冷先当震荡里的冷热看，不要当成趋势还会一路走下去。"
    if "偏强" in trend.title:
        how = "短线偏强时，KDJ/RSI 偏热也可能维持一阵，不能只因超买就当成一定要跌。"
    elif "偏弱" in trend.title:
        how = "短线偏弱时，超卖也可能维持一阵，不能只因偏冷就当抄底。"
    evi1 = list(trend.evidence[:3])
    if adx_last is not None:
        evi1.append(f"ADX {adx_last:.1f}" + ("，趋势在加强的说法更站得住" if adx_last >= 25 else "，趋势不算强，更接近震荡"))
        if adx_last >= 25 and "震荡" in trend.title:
            how = "均线像震荡，但 ADX 偏高，冷热指标不要只按超买超卖来读。"
    evi1.append(how)
    guides.append(GuideBlock(title="行情类型：先分趋势还是震荡", evidence=evi1))

    vol = series.get("amount") or series.get("vol") or []
    obv = series.get("OBV") or []
    evi2: list[str] = []
    if vol and len(vol) >= 6:
        last_v = float(vol[-1])
        avg5 = sum(float(x) for x in vol[-6:-1]) / 5
        if avg5:
            rel = last_v / avg5
            evi2.append(f"最近一日成交相对前 5 日均值约 {rel:.2f} 倍")
            if rel >= 1.5:
                evi2.append("量明显放大，价格变动更值得对照。")
            elif rel <= 0.6:
                evi2.append("量明显缩小，涨跌可能不牢。")
            if (
                rel >= 1.2
                and len(close) >= 2
                and close[-2]
                and close[-1] / close[-2] - 1 <= -0.03
            ):
                evi2.append("当日放量下跌，抛压真实，短线别急着接。")
    if close and obv and len(close) >= 6 and len(obv) >= 6:
        d_c = float(close[-1]) - float(close[-6])
        d_o = float(obv[-1]) - float(obv[-6])
        if d_c > 0 and d_o < 0:
            evi2.append("近 5 日价涨、OBV 走低，量价不一致。")
        elif d_c < 0 and d_o > 0:
            evi2.append("近 5 日价跌、OBV 走高，量价不一致。")
        else:
            evi2.append("近 5 日价格和 OBV 大致同向。")
    if not evi2:
        evi2.append("成交量或 OBV 不够，量价暂时对不上。")
    guides.append(GuideBlock(title="量价：涨跌有没有量跟着", evidence=evi2))

    evi3: list[str] = []
    if len(close) >= 20:
        dd = _max_drawdown(close)
        peak = max(close)
        last = close[-1]
        from_peak = last / peak - 1 if peak else 0.0
        ch20 = _pct_change(close, 20)
        evi3.append(f"这段日 K 里，从高点算最大回撤约 {dd:.1%}")
        evi3.append(f"现价相对这段最高点 {from_peak:.1%}")
        if ch20 is not None:
            evi3.append(f"近 20 日涨跌 {ch20:.1%}")
            if ch20 > 0.05 and dd > 0.12:
                evi3.append("近端在涨，但这整段中间砸得也不浅；不要只看最近涨了多少。")
            elif ch20 > 0 and dd < 0.06:
                evi3.append("近端在涨，这段回撤也不深，持有体验相对稳。")
            elif ch20 < -0.05 and dd > 0.15:
                evi3.append("这段又跌又深回撤，翻本会慢。")
        evi3.append("这是这段 K 线走过的路径，不是某条买卖策略的胜率。")
    else:
        evi3.append("日 K 不够，算不清这段回撤。")
    guides.append(GuideBlock(title="这段好不好拿：别只看涨了多少", evidence=evi3))

    evi4: list[str] = []
    p5 = _pct_change(close, 5)
    p20 = _pct_change(close, 20)
    p60 = _pct_change(close, 60)
    parts = []
    if p5 is not None:
        parts.append(("近 5 日", p5))
        evi4.append(f"近 5 日 {p5:.1%}")
    if p20 is not None:
        parts.append(("近 20 日", p20))
        evi4.append(f"近 20 日 {p20:.1%}")
    if p60 is not None:
        parts.append(("近 60 日", p60))
        evi4.append(f"近 60 日 {p60:.1%}")
    if len(parts) >= 2:
        top = max(parts, key=lambda x: abs(x[1]))
        if abs(top[1]) >= 0.02:
            evi4.append(f"绝对值最大的是{top[0]}，近端强弱更偏这一段。")
    if vol and len(vol) >= 5:
        avg5a = sum(float(x) for x in vol[-5:]) / 5
        evi4.append(f"近 5 日日均成交约 {_fmt_money(avg5a)}")
        if avg5a < 5e7:
            evi4.append("成交偏少，进出可能滑点大。")
        else:
            evi4.append("近 5 日成交还算活跃。")
    elif not parts:
        evi4.append("日 K 不够，5/20/60 日涨跌算不全。")
    guides.append(GuideBlock(title="近强从哪来：5 日 / 20 日 / 60 日", evidence=evi4))
    return guides


def enrich_with_account(
    report: TechReport,
    *,
    cash_total: float = 0.0,
    cash_known: bool = False,
    position_value: float = 0.0,
    book_value: float = 0.0,
    cost: float | None = None,
    price: float | None = None,
) -> TechReport:
    """Attach cash / cost context to a tech stance. Prefer 盈亏 over 集中度."""
    stance = report.stance
    evidence = list(report.stance_evidence)

    if cash_known:
        evidence.append(f"手头可用现金约 {cash_total:.2f} 元（手填）。")
    else:
        evidence.append("可用现金还没填，加仓能不能做还不清楚。")

    pnl_pct = None
    if cost is not None and price is not None and cost:
        pnl_pct = price / cost - 1
        evidence.append(
            f"相对成本 {cost:.4f}，现价 {price:.4f}，幅度 {pnl_pct:.1%}"
        )

    bullish = "加仓" in stance and "观望" not in stance
    bearish = "减" in stance

    if bullish and cash_known and cash_total <= 0:
        stance = "指标偏多，但手头几乎没有可用现金，更宜观望，先别加仓。"
    elif bullish and cash_known and book_value > 0 and cash_total < book_value * 0.05:
        stance = "指标偏多，但现金很少，更宜观望或只用很少一点试。"
    elif bearish and pnl_pct is not None and pnl_pct < -0.03:
        stance = (
            "指标偏空。相对你的成本还在亏；现在减会把账面亏损变成实亏。"
            "要不要动，取决于你更在意兑现这笔亏损，还是更在意后面可能继续跌。"
        )
    elif bearish and pnl_pct is not None and pnl_pct > 0.03:
        stance = (
            "指标偏空。相对成本还在赚；现在减是落袋为安，不减则账面盈利还可能吐回去。"
        )
    elif bearish and cash_known and cash_total < max(1000.0, book_value * 0.05 if book_value else 0):
        stance = stance.rstrip("。") + "。现金也不多；若减仓，先想清楚是为了止亏还是留钱以后再用。"

    return replace(report, stance=stance, stance_evidence=evidence)


def analyze_indicators(series: dict[str, list[float]]) -> TechReport:
    """series: column name -> list of floats (oldest→newest)."""
    items: list[TechItem] = []
    for handler in _HANDLERS:
        it = handler(series)
        if it:
            if not it.about:
                it.about = _about(it.name)
            items.append(it)
    taken = {i.name for i in items}
    quiet_extra = _quiet_from_series(series, taken)
    for q in quiet_extra:
        if not q.about:
            q.about = _about(q.name)
    signals = [i for i in items if i.signal]
    quiet = [i for i in items if not i.signal] + quiet_extra
    stance, stance_evi = _stance(signals)
    trend = judge_trend(series)
    return TechReport(
        stance=stance,
        stance_evidence=stance_evi,
        signals=signals,
        quiet=quiet,
        trend_title=trend.title,
        trend_evidence=list(trend.evidence),
        guides=build_guides(series, trend),
    )


def series_from_dataframe(df) -> dict[str, list[float]]:
    """Build series dict from a pandas DataFrame with indicator columns."""
    out: dict[str, list[float]] = {}
    if df is None or df.empty:
        return out
    for col in df.columns:
        if col in ("datetime",):
            continue
        try:
            out[str(col)] = [float(x) for x in df[col].tolist() if x == x]
        except (TypeError, ValueError):
            continue
    return out


def analyze_kline(df) -> TechReport:
    """Compute all easy-tdx indicators on daily kline then analyze."""
    from easy_tdx.indicator import compute_indicators, list_indicators
    from easy_tdx.MyTT import MA

    if df is None or getattr(df, "empty", True):
        return TechReport(
            stance="没有够用的日 K，算不了技术指标。",
            stance_evidence=["日 K 为空"],
            signals=[],
            quiet=[],
        )
    names = [x["name"] for x in list_indicators()]
    enriched = compute_indicators(df.copy(), names)
    # simple MAs for arrangement
    closes = enriched["close"].astype(float)
    enriched["MA5"] = MA(closes, 5)
    enriched["MA10"] = MA(closes, 10)
    enriched["MA20"] = MA(closes, 20)
    return analyze_indicators(series_from_dataframe(enriched))
