from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PlanLevel:
    level: float
    label: str


@dataclass
class PlanScenario:
    case: str
    action: str


@dataclass
class TomorrowView:
    title: str = ""
    open_bias: str = ""
    band: str = ""
    watches: list[str] = field(default_factory=list)
    note: str = "把预案收成明天要用的几条：默认动作、竞价偏向、关注区间。不是点位预测，也不能保证开盘方向。"


@dataclass
class PlanView:
    has: bool = False
    price: float = 0.0
    ma5: float | None = None
    defenses: list[PlanLevel] = field(default_factory=list)
    confirm: str = ""
    principles: list[str] = field(default_factory=list)
    scenarios: list[PlanScenario] = field(default_factory=list)
    tomorrow: TomorrowView | None = None
    note: str = (
        "点位由规则根据现价、均线和近期底部拼的，随每天数据刷新；"
        "是预案不是保证，盘中对号入座就行。"
    )


def _f(val) -> float | None:
    try:
        v = float(val)
    except (TypeError, ValueError):
        return None
    if v != v:
        return None
    return v


def _ma(df, last, col: str, n: int) -> float | None:
    """行里有现成均线列就用；没有（如原始日 K）就自己用收盘价算。"""
    v = _f(last.get(col))
    if v is not None:
        return v
    if "close" not in df.columns or len(df) < n:
        return None
    return _f(df["close"].tail(n).mean())


def _fmt_bottom(date) -> str:
    s = str(date or "")[:10]
    try:
        return f"{int(s[5:7])}-{int(s[8:10])} 底"
    except (ValueError, IndexError):
        return "近期底"


def build_plan(
    df,
    fractals: list[dict] | None = None,
    *,
    cost: float | None = None,
    cash_total: float | None = None,
    book_value: float | None = None,
) -> PlanView:
    """从日 K + 缠论底部分型 + 账户状态拼操作预案。纯函数，不联网。"""
    out = PlanView()
    if df is None or getattr(df, "empty", True) or len(df) < 2:
        return out
    last = df.iloc[-1]
    prev = df.iloc[-2]
    price = _f(last.get("close"))
    prev_close = _f(prev.get("close"))
    if not price or not prev_close:
        return out
    out.price = price
    ma5 = _ma(df, last, "ma5", 5)
    out.ma5 = ma5
    ma20 = _ma(df, last, "ma20", 20)
    ma60 = _ma(df, last, "ma60", 60)

    candidates: list[tuple[float, int, str]] = []
    for fx in fractals or []:
        if fx.get("type") != "di" or not fx.get("done", True):
            continue
        v = _f(fx.get("val"))
        if v is None or v >= price:
            continue
        candidates.append((v, 0, _fmt_bottom(fx.get("date"))))
    for priority, (mv, label) in enumerate(((ma20, "MA20"), (ma60, "MA60")), start=1):
        if mv and mv < price:
            candidates.append((mv, priority, label))
    if not candidates and "low" in df.columns:
        low20 = _f(df["low"].tail(20).min())
        if low20 and low20 < price:
            candidates.append((low20, 2, "近 20 日最低"))
    candidates.sort(key=lambda c: (-c[0], c[1]))
    for v, _, label in candidates:
        if any(abs(v - d.level) / d.level < 0.005 for d in out.defenses):
            continue
        out.defenses.append(PlanLevel(round(v, 4), label))
        if len(out.defenses) >= 3:
            break
    if not out.defenses:
        return out
    out.has = True

    if ma5:
        if price < ma5:
            out.confirm = (
                f"收复 MA5（现 {ma5:.3f}，每天会下移）才算右侧确认；"
                "在那之前，反弹只当反抽看。"
            )
        else:
            out.confirm = (
                f"现价在 MA5（{ma5:.3f}）上方，短线动能没坏；"
                "跌回 MA5 下方则确认失败。"
            )

    principles = out.principles
    change = price / prev_close - 1
    vr = None
    if "vol" in df.columns and len(df) >= 7:
        base = _f(df["vol"].iloc[-6:-1].mean())
        vol = _f(last.get("vol"))
        if base and vol is not None:
            vr = vol / base
    if change <= -0.03 and vr is not None and vr >= 1.2:
        principles.append(
            "刚收一根放量大阴线，次日默认不是加仓日；"
            "除非首道防线附近出现明确的缩量企稳。"
        )
    if cost and cost > 0:
        pnl = price / cost - 1
        if pnl <= -0.05:
            principles.append(
                f"相对成本 {cost:.4f} 已浮亏约 {-pnl:.1%}，"
                "别为了摊低成本而加仓。"
            )
    if book_value is not None:
        denom = book_value + (cash_total or 0.0)
        if denom > 0 and book_value / denom >= 0.6:
            principles.append(
                f"整体仓位约 {book_value / denom:.0%}，偏重；先把“不动”当默认动作。"
            )
    if cash_total:
        principles.append(
            f"手头现金约 {cash_total:.0f} 元，是等信号用的：要么缩量企稳，要么右侧确认。"
        )
    principles.append("防守位从近到远排；每跌破一道，看空权重加一分。")

    d1 = out.defenses[0]
    d2 = out.defenses[1] if len(out.defenses) > 1 else None
    scenarios = out.scenarios
    if ma5 and price < ma5:
        scenarios.append(
            PlanScenario(f"收复 MA5（≈{ma5:.3f}）", "右侧确认成立；回踩不破可考虑补")
        )
    elif ma5:
        scenarios.append(
            PlanScenario(f"守住 MA5（≈{ma5:.3f}）", "右侧仍成立；跌回 MA5 下方转防守")
        )
    if d2:
        scenarios.append(
            PlanScenario(
                f"下探 {d1.level:.3f}–{d2.level:.3f} 一带缩量企稳",
                f"可小仓试一笔；跌破 {d2.level:.3f}（{d2.label}）认错",
            )
        )
    else:
        scenarios.append(
            PlanScenario(
                f"回踩 {d1.level:.3f}（{d1.label}）缩量企稳",
                "可小仓试一笔；有效跌破就认错",
            )
        )
    scenarios.append(
        PlanScenario(
            f"放量跌破 {d1.level:.3f}（{d1.label}）",
            f"不补，先想防守；下看 {d2.level:.3f}" if d2 else "不补，先想防守",
        )
    )
    if ma5 and price < ma5:
        scenarios.append(
            PlanScenario(f"在 {d1.level:.3f} 与 MA5 之间横盘", "观望，现金留着")
        )
    out.tomorrow = build_tomorrow(out)
    return out


def _open_bias(overseas) -> str:
    if overseas is None or not getattr(overseas, "ok", False):
        return "竞价方向看今晚外盘，现在还没数。"
    blob = (getattr(overseas, "title", "") or "") + "".join(
        getattr(overseas, "evidence", None) or []
    )
    if "承压" in blob or "低开" in blob:
        return "外盘偏空，明天竞价先按承压准备。"
    if "有支撑" in blob or "高开" in blob:
        return "外盘偏多，明天竞价先按有情绪准备。"
    if "安静" in blob or "幅度一般" in blob:
        return "外盘不算剧烈，明天竞价别对外盘预期太高。"
    return "外盘有数，但没有一边倒的信号。"


def build_tomorrow(plan: PlanView, overseas=None) -> TomorrowView:
    """把预案收成明天的默认动作。overseas 有就补竞价偏向。"""
    out = TomorrowView()
    if not plan.has:
        return out
    blob = "".join(plan.principles)
    ma5 = plan.ma5
    d1 = plan.defenses[0] if plan.defenses else None
    if "不是加仓日" in blob:
        out.title = "明日默认观望，不是加仓日。"
    elif ma5 and plan.price >= ma5 * 0.998:
        out.title = f"明日默认防守：先看能不能守住 MA5（{ma5:.3f}）。"
    elif d1:
        ma5_s = f"{ma5:.3f}" if ma5 else "MA5"
        out.title = (
            f"明日默认观望；收到 {d1.level:.3f}（{d1.label}）一带缩量，"
            f"或收复 MA5（{ma5_s}），再谈动手。"
        )
    else:
        out.title = "明日默认观望。"
    out.open_bias = _open_bias(overseas)
    if d1 and ma5:
        lo, hi = (d1.level, ma5) if d1.level <= ma5 else (ma5, d1.level)
        out.band = f"明天先看 {lo:.3f}–{hi:.3f}（防线到 MA5），出了这段才重新定性。"
    elif d1:
        out.band = f"明天先看首道防线 {d1.level:.3f}（{d1.label}）是否守得住。"
    out.watches = [f"{s.case} → {s.action}" for s in plan.scenarios[:3]]
    return out
