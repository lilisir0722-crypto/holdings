from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta

from holdings.tech import BoardBlock, InfoBlock, TechReport, TrendJudgment, judge_trend


def trend_side(title: str) -> str:
    if "偏强" in (title or ""):
        return "多"
    if "偏弱" in (title or ""):
        return "空"
    return "中"


def _label(trend: TrendJudgment | None) -> str:
    if trend is None:
        return "没有"
    title = (trend.title or "").rstrip("。")
    if "算不清" in title:
        return "没有"
    if "偏强" in title:
        return "偏强"
    if "偏弱" in title:
        return "偏弱"
    if "震荡" in title:
        return "震荡"
    return title or "没有"


def summarize_timeframes(
    daily: TrendJudgment | None,
    weekly: TrendJudgment | None,
    min60: TrendJudgment | None,
) -> InfoBlock:
    parts = [
        f"日线{_label(daily)}",
        f"周线{_label(weekly)}",
        f"60 分钟{_label(min60)}",
    ]
    title = "，".join(parts) + "。"
    evidence: list[str] = []
    for name, tr in (("日线", daily), ("周线", weekly), ("60 分钟", min60)):
        if tr is None:
            evidence.append(f"{name}暂时没有")
            continue
        evidence.append(f"{name}：{tr.title.rstrip('。')}")
        evidence.extend(list(tr.evidence)[:2])
    ok = any(tr is not None and "算不清" not in (tr.title or "") for tr in (daily, weekly, min60))
    return InfoBlock(title=title, evidence=evidence, ok=ok)


def apply_timeframe_stance(
    report: TechReport,
    *,
    daily: TrendJudgment | None,
    weekly: TrendJudgment | None,
    min60: TrendJudgment | None,
) -> TechReport:
    sides = []
    for tr in (daily, weekly, min60):
        if tr is None or "算不清" in (tr.title or ""):
            continue
        side = trend_side(tr.title)
        if side in ("多", "空"):
            sides.append(side)
    conflict = "多" in sides and "空" in sides
    if not conflict:
        return report
    who = (
        f"日线{_label(daily)}，周线{_label(weekly)}，60 分钟{_label(min60)}。"
        "哪一档在顶、哪一档顶不住，以这一句为准。"
    )
    evidence = list(report.stance_evidence)
    evidence.append(who)
    return replace(
        report,
        stance="多周期对不上，更宜观望。",
        stance_evidence=evidence,
    )


def _pct(close: list[float] | None, days: int) -> float | None:
    if not close or len(close) < days + 1:
        return None
    old = float(close[-(days + 1)])
    last = float(close[-1])
    if not old:
        return None
    return last / old - 1


def _vs_word(mine: float | None, other: float | None) -> str:
    if mine is None or other is None:
        return "对不上"
    if mine > other + 0.002:
        return "相对强"
    if mine < other - 0.002:
        return "相对弱"
    return "差不多"


def _fmt_pct(v: float | None) -> str:
    if v is None:
        return "不够"
    return f"{v:.1%}"


def summarize_relative(
    self_close: list[float] | None,
    hs300_close: list[float] | None,
    board_name: str | None,
    board_close: list[float] | None,
    board_pcts: dict[int, float] | None = None,
) -> InfoBlock:
    evidence: list[str] = []
    ok = False
    board_pcts = board_pcts or {}
    for days in (5, 20, 60):
        mine = _pct(self_close, days)
        hs = _pct(hs300_close, days)
        board = _pct(board_close, days)
        if board is None:
            board = board_pcts.get(days)
        if mine is not None:
            ok = True
        line = f"近 {days} 日这只 {_fmt_pct(mine)}，沪深300 {_fmt_pct(hs)}（{_vs_word(mine, hs)}）"
        if board_name:
            line += f"；{board_name} {_fmt_pct(board)}（{_vs_word(mine, board)}）"
        evidence.append(line)
    if not ok:
        return InfoBlock(title="相对强弱暂时对不上", evidence=["日 K 不够，5/20/60 日算不全"], ok=False)
    return InfoBlock(title="相对沪深300和所属板块的近端强弱", evidence=evidence, ok=True)


def _code_key(value) -> str:
    s = str(value).strip()
    if s.endswith(".0"):
        s = s[:-2]
    digits = "".join(ch for ch in s if ch.isdigit())
    return digits.zfill(6)[-6:] if digits else s


def attach_board_ranks(
    boards: list[BoardBlock],
    *,
    rank_1d,
    rank_20d,
) -> list[BoardBlock]:
    def _frames(val):
        if val is None:
            return []
        if isinstance(val, list):
            return val
        return [val]

    def _lookup(df, code: str) -> tuple[int | None, float | None]:
        if df is None or getattr(df, "empty", True):
            return None, None
        want = _code_key(code)
        for i, raw in enumerate(df.to_dict(orient="records"), start=1):
            row_code = raw.get("code") or raw.get("board_code")
            if row_code is None:
                continue
            if _code_key(row_code) != want:
                continue
            place = raw.get("_place", i)
            try:
                place_i = int(place)
            except (TypeError, ValueError):
                place_i = i
            chg = raw.get("change_pct")
            try:
                return place_i, float(chg)
            except (TypeError, ValueError):
                return place_i, None
        return None, None

    def _lookup_any(val, code: str) -> tuple[int | None, float | None]:
        for df in _frames(val):
            place, chg = _lookup(df, code)
            if place is not None:
                return place, chg
        return None, None

    out: list[BoardBlock] = []
    for b in boards:
        evidence = list(b.evidence)
        code = ""
        if "（" in b.title and "）" in b.title:
            code = b.title.rsplit("（", 1)[-1].rstrip("）")
        if not code:
            out.append(b)
            continue
        place1, chg1 = _lookup_any(rank_1d, code)
        place20, chg20 = _lookup_any(rank_20d, code)
        if place1 is None and place20 is None:
            evidence.append("榜上暂无")
        else:
            if place1 is not None:
                extra = f"，涨跌 {chg1:.2f}%" if chg1 is not None else ""
                evidence.append(f"当日榜第 {place1}{extra}")
            if place20 is not None:
                extra = f"，涨跌 {chg20:.2f}%" if chg20 is not None else ""
                evidence.append(f"近 20 日榜第 {place20}{extra}")
        out.append(
            BoardBlock(
                title=b.title,
                evidence=evidence,
                ok=b.ok,
                summary_line=b.summary_line,
            )
        )
    return out


def _finite(val) -> float | None:
    if val is None:
        return None
    try:
        v = float(val)
    except (TypeError, ValueError):
        return None
    if v != v:
        return None
    return v


def summarize_intraday(tick_df, auction_df, prev_close: float | None) -> InfoBlock:
    evidence: list[str] = []
    ok = False
    if auction_df is not None and not getattr(auction_df, "empty", True):
        last = auction_df.iloc[-1]
        price = _finite(last.get("price") if hasattr(last, "get") else last["price"])
        matched = _finite(last.get("matched") if hasattr(last, "get") else last["matched"])
        if price is not None:
            ok = True
            if prev_close:
                chg = price / prev_close - 1
                evidence.append(f"竞价 {price:.4f}，相对昨收 {chg:.2%}")
            else:
                evidence.append(f"竞价 {price:.4f}")
        if matched is not None:
            evidence.append(f"竞价成交量 {matched:.0f}")
    if tick_df is not None and not getattr(tick_df, "empty", True):
        prices = [_finite(v) for v in tick_df["price"].tolist()]
        prices = [p for p in prices if p is not None]
        if prices:
            ok = True
            open_p, last_p = prices[0], prices[-1]
            high_p, low_p = max(prices), min(prices)
            evidence.append(f"分时开 {open_p:.4f}，最高 {high_p:.4f}，最低 {low_p:.4f}，最新 {last_p:.4f}")
            if prev_close:
                evidence.append(f"最新相对昨收 {last_p / prev_close - 1:.2%}")
            span = high_p - open_p
            drop = high_p - last_p
            if span > 0 and drop >= span * 0.4 and last_p < high_p:
                evidence.append("冲高后有回落。")
            elif last_p >= open_p and last_p >= (open_p + high_p) / 2:
                evidence.append("当天偏冲高。")
            elif last_p < open_p:
                evidence.append("当天相对开盘偏回落。")
            else:
                evidence.append("当天分时在开盘附近晃。")
            if high_p > low_p:
                close_pos = (last_p - low_p) / (high_p - low_p)
                if close_pos <= 0.15:
                    evidence.append("收在全天低位附近，尾盘没什么承接。")
                elif close_pos >= 0.85:
                    evidence.append("收在全天高位附近。")
    if not ok:
        return InfoBlock(title="今天没有分时", evidence=["分时或竞价暂时没有"], ok=False)
    title = "今天有分时"
    if any("回落" in e for e in evidence):
        title = "今天分时有回落"
    elif any("冲高" in e for e in evidence):
        title = "今天分时偏冲高"
    return InfoBlock(title=title, evidence=evidence, ok=True)


def _xdxr_date(row: dict) -> date | None:
    try:
        y = int(row.get("year"))
        m = int(row.get("month"))
        d = int(row.get("day"))
        return date(y, m, d)
    except (TypeError, ValueError):
        return None


def _is_split(row: dict) -> bool:
    cat = row.get("category")
    try:
        if int(cat) in (11, 12):
            return True
    except (TypeError, ValueError):
        pass
    name = str(row.get("name") or "")
    if "拆" in name or "扩缩" in name:
        return True
    suogu = _finite(row.get("suogu"))
    return suogu is not None and suogu != 0


def summarize_xdxr(df, *, as_of: date | None = None) -> InfoBlock:
    as_of = as_of or date.today()
    cutoff = date(as_of.year - 2, as_of.month, as_of.day) if as_of.month != 2 or as_of.day != 29 else date(as_of.year - 2, 2, 28)
    split_cut = as_of - timedelta(days=180)
    if df is None or getattr(df, "empty", True):
        return InfoBlock(title="除权记录暂时没有", evidence=["除权表为空"], ok=False)
    names = {
        1: "除权除息",
        5: "股本变化",
        11: "扩缩股",
        12: "非流通股缩股",
    }
    rows = []
    recent_split = False
    for raw in df.to_dict(orient="records"):
        dt = _xdxr_date(raw)
        if dt is None or dt < cutoff:
            continue
        cat = raw.get("category")
        try:
            cat_i = int(cat)
        except (TypeError, ValueError):
            cat_i = 0
        label = names.get(cat_i) or str(raw.get("name") or "除权")
        bits = [dt.isoformat(), label]
        fenhong = _finite(raw.get("fenhong"))
        song = _finite(raw.get("songzhuangu"))
        suogu = _finite(raw.get("suogu"))
        if fenhong:
            bits.append(f"分红 {fenhong}")
        if song:
            bits.append(f"送转 {song}")
        if suogu:
            bits.append(f"缩股 {suogu}")
        rows.append(" ".join(bits))
        if _is_split(raw) and dt >= split_cut:
            recent_split = True
    if not rows:
        return InfoBlock(title="近两年没有除权除息记录", evidence=["表里近 24 个月没有事件"], ok=False)
    evidence = rows[:12]
    if recent_split:
        evidence.append("近期有拆分，成本和未复权图可能对不齐；本页走势按前复权算。")
    title = f"近两年有 {len(rows)} 条除权除息"
    if recent_split:
        title = "近期有拆分，" + title
    return InfoBlock(title=title, evidence=evidence, ok=True)


def is_listed_etf(code: str) -> bool:
    c = (code or "").strip()
    if len(c) != 6 or not c.isdigit():
        return False
    return c.startswith(("15", "16", "18", "50", "51", "52", "56", "58"))


def parse_eastmoney_etf_quote(raw: dict | None) -> dict:
    data = (raw or {}).get("data") or {}
    out: dict = {}
    price = data.get("f43")
    iopv = data.get("f46")
    size = data.get("f116")
    if size in (None, "-"):
        size = data.get("f117")
    name = data.get("f58")
    if isinstance(price, (int, float)):
        out["price"] = float(price)
    if isinstance(iopv, (int, float)):
        out["iopv"] = float(iopv)
    if isinstance(size, (int, float)):
        out["size"] = float(size)
    if name:
        out["name"] = str(name)
    return out


def _fmt_money(x: float) -> str:
    ax = abs(x)
    if ax >= 1e8:
        return f"{x / 1e8:.2f} 亿"
    if ax >= 1e4:
        return f"{x / 1e4:.0f} 万"
    return f"{x:.0f} 元"


def summarize_etf(
    parsed: dict | None,
    *,
    track_60: float | None = None,
    self_60: float | None = None,
    gmbd: list[dict] | None = None,
) -> InfoBlock:
    parsed = parsed or {}
    price = parsed.get("price")
    iopv = parsed.get("iopv")
    size = parsed.get("size")
    evidence: list[str] = []
    if price is not None and iopv:
        prem = price / iopv - 1
        word = "溢价" if prem >= 0 else "折价"
        evidence.append(f"现价 {price:.4f}，IOPV {iopv:.4f}，{word} {abs(prem):.1%}")
        if abs(prem) >= 0.03:
            evidence.append("折溢价偏大，先核对 IOPV 时点（可能不是收盘值）；折价不等于便宜。")
        title = f"{word} {abs(prem):.1%}"
    elif price is not None:
        evidence.append(f"现价 {price:.4f}，IOPV 暂无")
        title = "溢价暂无"
    else:
        title = "ETF 溢价/规模暂无"
    if size is not None:
        evidence.append(f"规模约 {_fmt_money(size)}")
    else:
        evidence.append("规模暂无")
    if track_60 is not None and self_60 is not None:
        evidence.append(f"近 60 日这只 {self_60:.1%}，跟踪指数 {track_60:.1%}，差 {abs(self_60 - track_60):.1%}")
    else:
        evidence.append("跟踪误差暂无")
    share_rows = [r for r in (gmbd or []) if r.get("shares") not in (None, "", "---")]
    if share_rows:
        evidence.append(
            "份额（亿份）：" + "；".join(f"{r['date']} {r['shares']}" for r in share_rows[:3])
        )
        flow = next(
            (r for r in (gmbd or []) if r.get("subs") not in (None, "", "---")),
            None,
        )
        if flow:
            evidence.append(
                f"最近一期（{flow['date']}）申购 {flow['subs']} 亿份、赎回 {flow['redm']} 亿份"
            )
        evidence.append("份额趋势向上 = 资金在涌入这只 ETF；拆分折算会让数字跳变，看趋势别看绝对值。")
    ok = bool(evidence and (price is not None or size is not None))
    if not ok:
        return InfoBlock(title="ETF 溢价/规模暂无", evidence=evidence, ok=False)
    return InfoBlock(title=title, evidence=evidence, ok=True)


def closes_from_df(df) -> list[float]:
    if df is None or getattr(df, "empty", True) or "close" not in getattr(df, "columns", []):
        return []
    out: list[float] = []
    for v in df["close"].tolist():
        n = _finite(v)
        if n is not None:
            out.append(n)
    return out


def trend_from_df(df) -> TrendJudgment | None:
    closes = closes_from_df(df)
    if not closes:
        return None
    return judge_trend({"close": closes})


def attach_tech_extras(report: TechReport, ctx: dict | None, *, code: str = "") -> TechReport:
    data = ctx or {}
    daily = None
    if report.trend_title:
        daily = TrendJudgment(title=report.trend_title, evidence=list(report.trend_evidence))
    else:
        daily = trend_from_df(data.get("daily_df"))
    weekly = trend_from_df(data.get("weekly_df"))
    min60 = trend_from_df(data.get("min60_df"))
    report.timeframes = summarize_timeframes(daily, weekly, min60)
    report = apply_timeframe_stance(report, daily=daily, weekly=weekly, min60=min60)

    self_close = closes_from_df(data.get("daily_df"))
    if not self_close and report.trend_evidence:
        pass
    hs = closes_from_df(data.get("hs300_df"))
    board_name = None
    board_close: list[float] = []
    board_pcts: dict[int, float] = {}
    klines = data.get("board_klines") or {}
    if isinstance(klines, dict) and klines:
        first_code = next(iter(klines))
        board_close = closes_from_df(klines[first_code])
        board_name = (data.get("board_names") or {}).get(first_code) or first_code
    pcts = data.get("board_pcts") or {}
    if isinstance(pcts, dict):
        board_pcts = {int(k): float(v) for k, v in pcts.items() if v is not None}
        board_name = board_name or data.get("board_name")
    report.relative = summarize_relative(self_close, hs, board_name, board_close, board_pcts)

    report.boards = attach_board_ranks(
        list(report.boards),
        rank_1d=data.get("board_rank_1d"),
        rank_20d=data.get("board_rank_20d"),
    )
    prev = None
    if self_close:
        prev = self_close[-1]
    # yesterday close: if daily has at least 2 bars, use previous
    daily_df = data.get("daily_df")
    if daily_df is not None and not getattr(daily_df, "empty", True) and "close" in daily_df.columns:
        closes = closes_from_df(daily_df)
        if len(closes) >= 2:
            prev = closes[-2]
        elif closes:
            prev = closes[-1]
    report.intraday = summarize_intraday(data.get("tick_df"), data.get("auction_df"), prev)
    report.xdxr = summarize_xdxr(data.get("xdxr_df"))
    if is_listed_etf(code):
        report.etf = summarize_etf(
            data.get("etf") or {},
            track_60=data.get("track_60"),
            self_60=_pct(self_close, 60),
            gmbd=data.get("etf_gmbd"),
        )
    else:
        report.etf = None
    return report
