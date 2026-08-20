"""操作前检查：对照预案看这笔买/卖合不合纪律。纯函数，不联网。

它不替你决策，只回答「和刚才写的预案对着干吗」。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from holdings.plan import PlanView

# 防线一带：落在 d1–d2 闭区间内（含两端 0.15% 容差），不是「靠近 d1 上方」
_BAND = 0.0015


@dataclass
class CheckView:
    side: str
    price: float
    qty: float
    amount: float
    verdict: str  # 符合 / 部分符合 / 不符合 / 没法对照
    title: str
    reasons: list[str] = field(default_factory=list)
    past: str = ""
    zone: str = ""


def _in_defense_band(price: float, plan: PlanView) -> bool:
    if not plan.defenses:
        return False
    d1 = plan.defenses[0].level
    if len(plan.defenses) >= 2:
        d2 = plan.defenses[1].level
        hi, lo = max(d1, d2), min(d1, d2)
        return lo * (1 - _BAND) <= price <= hi * (1 + _BAND)
    return abs(price - d1) / d1 <= 0.005


def locate(price: float, plan: PlanView) -> str:
    """price 落在预案的哪一档：right / defense / gap / below / other。"""
    if _in_defense_band(price, plan):
        return "defense"
    ma5 = plan.ma5
    d1 = plan.defenses[0].level if plan.defenses else None
    if ma5 and price >= ma5 * 0.998:
        return "right"
    if d1 and ma5 and d1 < price < ma5:
        return "gap"
    if d1 and price < d1:
        return "below"
    return "other"


def _past_note(side: str, journals: list[dict] | None) -> str:
    if not journals:
        return ""
    rec = journals[0]
    stance = rec.get("stance") or ""
    date_s = rec.get("date") or ""
    rec_px = rec.get("price")
    px_s = f"{rec_px:.4f}" if isinstance(rec_px, (int, float)) else "暂无"
    later = (rec.get("later") or {}).get("5d") or {}
    chg = later.get("chg_pct")
    chg_s = f"，5 个交易日后 {chg:+.1f}%" if isinstance(chg, (int, float)) else ""
    if side == "买" and any(k in stance for k in ("观望", "偏空", "偏卖", "不一致")):
        return (
            f"上一份快照（{date_s}，价 {px_s}）倾向「{stance}」{chg_s}。"
            "现在追买是和当时纪律对着干。"
        )
    if side == "卖" and any(k in stance for k in ("偏多", "偏买")):
        return (
            f"上一份快照（{date_s}，价 {px_s}）倾向「{stance}」{chg_s}。"
            "预案还没转空就减，要想清楚是降仓还是认错。"
        )
    return ""


def check_trade(
    *,
    side: str,
    price: float,
    qty: float,
    plan: PlanView,
    cash: float | None = None,
    book: float | None = None,
    hold_qty: float | None = None,
    cost: float | None = None,
    journals: list[dict] | None = None,
) -> CheckView:
    side = (side or "").strip()
    try:
        price_f = float(price)
        qty_f = float(qty)
    except (TypeError, ValueError):
        price_f, qty_f = 0.0, 0.0
    amount = price_f * qty_f if price_f > 0 and qty_f > 0 else 0.0
    out = CheckView(
        side=side, price=price_f, qty=qty_f, amount=amount, verdict="没法对照", title=""
    )
    if side not in ("买", "卖") or price_f <= 0 or qty_f <= 0:
        out.title = "价格、数量要大于 0，方向选买或卖。"
        out.reasons = ["填完再对照。"]
        return out
    if not plan.has:
        out.title = "这只暂时拼不出预案，纪律无从对照。"
        out.reasons = ["K 线不够或没有防守位时，先别用这笔去赌。"]
        return out

    zone = locate(price_f, plan)
    out.zone = zone
    d1 = plan.defenses[0]
    d2 = plan.defenses[1] if len(plan.defenses) > 1 else None
    blob = "".join(plan.principles)
    reasons: list[str] = []
    warn = 0
    block = 0

    if side == "买":
        if zone == "gap":
            block += 1
            ma5_s = f"{plan.ma5:.3f}" if plan.ma5 else "MA5"
            reasons.append(
                f"不符合：{price_f:.3f} 夹在首道防线 {d1.level:.3f}（{d1.label}）"
                f"和右侧确认 {ma5_s} 中间，两头不靠。"
                "预案是跌到防线一带缩量企稳，或收复 MA5 再右侧追。"
            )
        elif zone == "below":
            block += 1
            nxt = f"下看 {d2.level:.3f}（{d2.label}）" if d2 else "先想防守"
            reasons.append(
                f"不符合：{price_f:.3f} 已在首道防线 {d1.level:.3f} 下方，预案说不补，{nxt}。"
            )
        elif zone == "defense":
            reasons.append(
                f"位置对上了：{price_f:.3f} 在防线一带"
                f"（{d1.level:.3f}"
                + (f"–{d2.level:.3f}" if d2 else "")
                + "），预案说可小仓试一笔。"
            )
        elif zone == "right":
            reasons.append(
                f"位置对上了：{price_f:.3f} 在 MA5"
                f"（{plan.ma5:.3f}）上方，算右侧确认。"
            )
        else:
            warn += 1
            reasons.append(f"{price_f:.3f} 没落在预案写明的档上，对不上号就先当观望。")

        if "默认不是加仓日" in blob:
            if zone == "defense":
                warn += 1
                reasons.append("刚收过放量大阴线，虽在防线一带，仍要看到缩量企稳再动。")
            else:
                block += 1
                reasons.append("刚收过放量大阴线，预案说次日默认不是加仓日。")
        if "摊低成本" in blob:
            warn += 1
            cost_s = f"{cost:.4f}" if cost else "成本"
            reasons.append(f"相对 {cost_s} 已浮亏，别为了摊低成本而加仓。")
        if "偏重" in blob:
            warn += 1
            reasons.append("整体仓位已偏重，先把「不动」当默认动作。")
        if cash is not None and amount > cash:
            block += 1
            reasons.append(f"这笔约 {amount:.0f} 元，手头现金 {cash:.0f} 元不够。")
        elif cash is not None and cash > 0 and amount > cash * 0.4 and zone == "defense":
            warn += 1
            reasons.append(
                f"防线试仓预案写的是「小仓」，这笔约占现金 {amount / cash:.0%}，偏大。"
            )
    else:  # 卖
        if hold_qty is not None and qty_f > hold_qty + 1e-9:
            warn += 1
            reasons.append(f"要卖 {qty_f:g}，手里大约 {hold_qty:g}，数量对不上。")
        if zone == "below" or (plan.defenses and price_f <= d1.level):
            reasons.append(
                f"位置对上了：{price_f:.3f} 已触及/跌破首道防线 {d1.level:.3f}，预案说先想防守。"
            )
        elif zone == "right":
            warn += 1
            reasons.append(
                f"{price_f:.3f} 还在 MA5（{plan.ma5:.3f}）上方，预案右侧仍成立；"
                "现在卖是提前降仓，不是认错。"
            )
        elif zone == "gap":
            reasons.append(
                f"{price_f:.3f} 在防线和 MA5 之间。仓位偏重时反抽减一部分，预案允许；"
                "当突破去追卖就不合。"
            )
        else:
            warn += 1
            reasons.append("这笔卖和预案点位对不上，要想清楚是降仓、止盈还是认错。")
        if "偏重" in blob:
            reasons.append("整体仓位偏重，减一点和「先把不动当默认」不冲突。")

    past = _past_note(side, journals)
    out.past = past
    if past and side == "买":
        warn += 1

    if block:
        out.verdict = "不符合"
        out.title = f"这笔{side}不符合预案。"
    elif warn:
        out.verdict = "部分符合"
        out.title = f"这笔{side}和预案只对上一部分。"
    else:
        out.verdict = "符合"
        out.title = f"这笔{side}和预案对得上。"
    out.reasons = reasons
    return out
