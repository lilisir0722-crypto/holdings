from dataclasses import dataclass, field


@dataclass
class PositionSnapshot:
    code: str
    name: str
    kind: str
    quantity: float
    cost: float
    price: float | None = None
    high_120: float | None = None
    low_120: float | None = None
    announcements: list[str] = field(default_factory=list)
    change_20d_pct: float | None = None
    daily_returns: list[float] = field(default_factory=list)
    place: str = ""
    top_holdings: list[str] = field(default_factory=list)
    holdings_asof: str = ""


@dataclass
class MarketSnapshot:
    code: str
    name: str
    price: float | None = None
    day_change_pct: float | None = None
    change_20d_pct: float | None = None
    high_120: float | None = None
    low_120: float | None = None
    error: str | None = None
    daily_returns: list[float] = field(default_factory=list)


@dataclass
class Judgment:
    title: str
    evidence: list[str]
    level: str = "info"
    kind: str = "提醒"


@dataclass
class PositionJudgment:
    snapshot: PositionSnapshot
    items: list[Judgment]
    market_value: float | None
    pnl_pct: float | None


@dataclass
class Report:
    overall: Judgment
    positions: list[PositionJudgment]
    total_value: float
    total_cost: float
    market: MarketSnapshot | None = None
    market_judgment: Judgment | None = None
    structure_judgment: Judgment | None = None


def _market_value(pos: PositionSnapshot) -> float | None:
    if pos.price is None:
        return None
    return pos.quantity * pos.price


def _pnl_pct(pos: PositionSnapshot) -> float | None:
    if pos.price is None or pos.cost == 0:
        return None
    return (pos.price - pos.cost) / pos.cost


def _range_place(pos: PositionSnapshot) -> tuple[str | None, float | None]:
    if (
        pos.price is None
        or pos.high_120 is None
        or pos.low_120 is None
        or pos.high_120 <= pos.low_120
    ):
        return None, None
    pct = (pos.price - pos.low_120) / (pos.high_120 - pos.low_120)
    if pct >= 0.7:
        return "在这段行情里偏高", pct
    if pct <= 0.3:
        return "在这段行情里偏低", pct
    return "在这段行情里靠中间", pct


def _vs_hs300(pos: PositionSnapshot, market: MarketSnapshot | None) -> tuple[str | None, str | None]:
    if (
        market is None
        or pos.change_20d_pct is None
        or market.change_20d_pct is None
    ):
        return None, None
    diff = pos.change_20d_pct - market.change_20d_pct
    mine = f"这只最近约 20 个交易日{( '涨' if pos.change_20d_pct >= 0 else '跌' )}了 {abs(pos.change_20d_pct):.1%}"
    bench = f"沪深300 同期{( '涨' if market.change_20d_pct >= 0 else '跌' )}了 {abs(market.change_20d_pct):.1%}"
    evidence = f"{mine}；{bench}"
    if diff <= -0.02:
        return "比沪深300弱", evidence
    if diff >= 0.02:
        return "比沪深300强", evidence
    return "和沪深300差不多", evidence


def _situation(pos: PositionSnapshot, total_value: float | None, market: MarketSnapshot | None = None) -> Judgment:
    pnl = _pnl_pct(pos)
    value = _market_value(pos)
    place, range_pct = _range_place(pos)
    parts: list[str] = []
    evidence: list[str] = []
    if pnl is not None:
        if pnl <= -0.03:
            parts.append(f"相对成本亏 {abs(pnl):.1%}")
        elif pnl >= 0.03:
            parts.append(f"相对成本赚 {pnl:.1%}")
        else:
            parts.append("相对成本和现价差不多")
        evidence.append(f"成本 {pos.cost:.4f}，现价 {pos.price:.4f}，幅度 {pnl:.1%}")
    if place:
        parts.append(place)
        evidence.append(
            f"这段行情最低 {pos.low_120:.4f}、最高 {pos.high_120:.4f}，现价在其中 {range_pct:.0%} 的位置"
        )
    if pos.change_20d_pct is not None:
        direction = "涨" if pos.change_20d_pct >= 0 else "跌"
        evidence.append(f"最近约 20 个交易日{direction}了 {abs(pos.change_20d_pct):.1%}")
    vs_title, vs_evi = _vs_hs300(pos, market)
    if vs_title:
        parts.append(vs_title)
        if vs_evi:
            evidence.append(vs_evi)
    if total_value and value:
        evidence.append(f"市值 {value:.2f} 元，占全部 {value / total_value:.0%}")
        add_value = pos.quantity * pos.price
        new_cost = (pos.cost + pos.price) / 2
        new_total = total_value + add_value
        new_share = (value + add_value) / new_total
        evidence.append(
            f"若按现价再买同样数量，成本会到 {new_cost:.4f}，这只占比大约到 {new_share:.0%}"
        )
    title = "，".join(parts) + "。" if parts else "有行情，但还拼不出一句话。"
    return Judgment(title=title, evidence=evidence, level="info", kind="现状")


def judge_one(
    pos: PositionSnapshot,
    total_value: float | None,
    market: MarketSnapshot | None = None,
) -> list[Judgment]:
    items: list[Judgment] = []
    value = _market_value(pos)

    if pos.price is None:
        items.append(
            Judgment(
                title="暂时没有行情，无法判断现在贵不贵",
                evidence=[f"{pos.code} 没有现价，行情没查到或连不上"],
                level="watch",
                kind="提醒",
            )
        )
        return items

    items.append(_situation(pos, total_value, market))

    if (
        total_value
        and value is not None
        and total_value > 0
        and abs(value - total_value) > 1e-6
        and value / total_value > 0.50
    ):
        pct = value / total_value * 100
        items.append(
            Judgment(
                title="这只在你现在这些里面占比偏高",
                evidence=[
                    f"{pos.name} 市值 {value:.2f} 元，占全部有行情持仓 {pct:.0f}%（超过 50%）"
                ],
                level="watch",
                kind="提醒",
            )
        )

    pnl = _pnl_pct(pos)
    if pnl is not None and pnl < -0.20:
        items.append(
            Judgment(
                title="相对你的成本亏得比较多",
                evidence=[
                    f"成本 {pos.cost:.4f}，现价 {pos.price:.4f}，幅度 {pnl:.1%}"
                ],
                level="alert",
                kind="提醒",
            )
        )
    if pnl is not None and pnl > 0.50:
        items.append(
            Judgment(
                title="相对成本赚得比较多",
                evidence=[
                    f"成本 {pos.cost:.4f}，现价 {pos.price:.4f}，幅度 {pnl:.1%}"
                ],
                level="info",
                kind="提醒",
            )
        )

    if pos.high_120 and pos.price >= pos.high_120 * 0.9:
        items.append(
            Judgment(
                title="价格靠近这段时间的高位",
                evidence=[
                    f"现价 {pos.price:.4f}，这段行情最高 {pos.high_120:.4f}"
                    + (f"、最低 {pos.low_120:.4f}" if pos.low_120 else "")
                ],
                level="watch",
                kind="提醒",
            )
        )
    if pos.low_120 and pos.price <= pos.low_120 * 1.1:
        items.append(
            Judgment(
                title="价格靠近这段时间的低位",
                evidence=[
                    f"现价 {pos.price:.4f}，这段行情最低 {pos.low_120:.4f}"
                    + (f"、最高 {pos.high_120:.4f}" if pos.high_120 else "")
                ],
                level="info",
                kind="提醒",
            )
        )

    if pos.announcements:
        items.append(
            Judgment(
                title="最近有公告，先读完再决定加不加",
                evidence=list(pos.announcements),
                level="watch",
                kind="提醒",
            )
        )

    return items


def _market_judgment(
    judged: list[PositionJudgment],
    market: MarketSnapshot,
) -> Judgment:
    evidence: list[str] = []
    if market.price is not None:
        evidence.append(f"沪深300（510300）现价 {market.price:.4f}")
    if market.day_change_pct is not None:
        d = "涨" if market.day_change_pct >= 0 else "跌"
        evidence.append(f"今日{d} {abs(market.day_change_pct):.2%}")
    if market.change_20d_pct is not None:
        d = "涨" if market.change_20d_pct >= 0 else "跌"
        evidence.append(f"最近约 20 个交易日{d}了 {abs(market.change_20d_pct):.1%}")
    if market.low_120 is not None and market.high_120 is not None and market.price:
        span = market.high_120 - market.low_120
        if span > 0:
            place = (market.price - market.low_120) / span
            evidence.append(
                f"这段行情最低 {market.low_120:.4f}、最高 {market.high_120:.4f}，现价在其中 {place:.0%} 的位置"
            )

    if market.change_20d_pct is None:
        return Judgment(
            title="沪深300 的这段涨跌暂时没算出来。",
            evidence=evidence or [market.error or "没有沪深300行情"],
            level="watch",
            kind="现状",
        )

    weighted = 0.0
    weight = 0.0
    for p in judged:
        if p.market_value and p.snapshot.change_20d_pct is not None:
            weighted += p.market_value * p.snapshot.change_20d_pct
            weight += p.market_value
    if weight:
        mine = weighted / weight
        diff = mine - market.change_20d_pct
        md = "涨" if mine >= 0 else "跌"
        bd = "涨" if market.change_20d_pct >= 0 else "跌"
        evidence.append(
            f"你现在这些按市值平均，最近约 20 个交易日{md}了 {abs(mine):.1%}"
        )
        if diff <= -0.02:
            vs = "比沪深300弱"
        elif diff >= 0.02:
            vs = "比沪深300强"
        else:
            vs = "和沪深300差不多"
        title = f"沪深300 最近约 20 个交易日{bd}了 {abs(market.change_20d_pct):.1%}。你手里这些{vs}。"
    else:
        bd = "涨" if market.change_20d_pct >= 0 else "跌"
        title = f"沪深300 最近约 20 个交易日{bd}了 {abs(market.change_20d_pct):.1%}。"

    return Judgment(title=title, evidence=evidence, level="info", kind="现状")


def _pair_corr(xs: list[float], ys: list[float]) -> float | None:
    n = min(len(xs), len(ys))
    if n < 20:
        return None
    a = xs[-n:]
    b = ys[-n:]
    mean_a = sum(a) / n
    mean_b = sum(b) / n
    cov = sum((x - mean_a) * (y - mean_b) for x, y in zip(a, b))
    var_a = sum((x - mean_a) ** 2 for x in a)
    var_b = sum((y - mean_b) ** 2 for y in b)
    if var_a == 0 or var_b == 0:
        return None
    return cov / (var_a ** 0.5 * var_b ** 0.5)


def _residual_corr(
    xs: list[float], ys: list[float], market: list[float]
) -> float | None:
    n = min(len(xs), len(ys), len(market))
    if n < 20:
        return None
    ra = [x - m for x, m in zip(xs[-n:], market[-n:])]
    rb = [y - m for y, m in zip(ys[-n:], market[-n:])]
    return _pair_corr(ra, rb)


def _theme_label(name: str) -> str | None:
    if "ETF" in name:
        left = name.split("ETF")[0].strip()
        return left or None
    return None


def _quote_word(pos: PositionSnapshot) -> str:
    code = pos.code.strip()
    if pos.kind == "基金" and not code.startswith(
        ("15", "16", "18", "50", "51", "52", "56", "58")
    ):
        return "净值"
    return "现价"


def _place_of(pos: PositionSnapshot) -> str:
    return pos.place.strip() or "佣金宝"


def _bucket(pos: PositionSnapshot) -> str:
    n = pos.name or ""
    if any(w in n for w in ("货币", "余额宝")):
        return "货币"
    if any(w in n for w in ("国债", "债券", "短债", "信用债", "利率债")):
        return "债券"
    return "股票"


_BROAD = ("沪深300", "中证500", "中证1000", "上证50")


def _mix_title(positions: list[PositionSnapshot]) -> tuple[str, list[str]]:
    by = {"股票": 0.0, "债券": 0.0, "货币": 0.0}
    total = 0.0
    for p in positions:
        v = _market_value(p)
        if v is None:
            continue
        by[_bucket(p)] += v
        total += v
    if not total:
        return "", []
    shares = {k: by[k] / total for k in by}
    present = [k for k in ("股票", "债券", "货币") if shares[k] >= 0.005]
    evidence = [f"{k} {by[k]:.2f} 元，约占 {shares[k]:.0%}" for k in present]
    if len(present) == 1:
        missing = [k for k in ("股票", "债券", "货币") if k not in present]
        title = f"现在填进来的几乎全是{present[0]}，没有{'或'.join(missing)}。"
    else:
        title = "、".join(f"{k}约 {shares[k]:.0%}" for k in present) + "。"
    return title, evidence


def _structure_judgment(
    positions: list[PositionSnapshot],
    market: MarketSnapshot | None = None,
) -> Judgment | None:
    mix_title, mix_evi = _mix_title(positions)
    movers = [p for p in positions if p.daily_returns]
    best: tuple[PositionSnapshot, PositionSnapshot, float] | None = None
    for i, left in enumerate(movers):
        for right in movers[i + 1 :]:
            corr = _pair_corr(left.daily_returns, right.daily_returns)
            if corr is None:
                continue
            if best is None or corr > best[2]:
                best = (left, right, corr)

    stock = [p for p in positions if _bucket(p) == "股票"]
    all_theme = bool(stock) and not any(
        any(b in p.name for b in _BROAD) for p in stock
    )
    labels: list[str] = []
    for p in stock:
        lab = _theme_label(p.name)
        if lab and lab not in labels:
            labels.append(lab)
    evidence: list[str] = list(mix_evi)
    corr = best[2] if best else None
    market_rets = list(market.daily_returns) if market else []
    residual = None
    if best and market_rets:
        residual = _residual_corr(
            best[0].daily_returns, best[1].daily_returns, market_rets
        )

    if corr is not None:
        if corr >= 0.6:
            how = "会比较一起动"
        elif corr >= 0.3:
            how = "有一点一起动"
        else:
            how = "不太一起动"
    else:
        how = ""

    parts: list[str] = []
    if mix_title:
        parts.append(mix_title)
    if all_theme and len(labels) >= 2:
        parts.append(f"一个{labels[0]}、一个{labels[1]}，行业不同。")
    elif all_theme and labels and len(stock) >= 2:
        parts.append(f"股票里现在填进来的都是{labels[0]}。")
    if residual is not None and residual < 0.2 and corr is not None and corr >= 0.3:
        parts.append("一起动主要是跟着大盘。")
    elif corr is not None:
        parts.append(f"最近涨跌相关大约 {corr:.2f}，{how}。")

    if not parts:
        return None
    title = "".join(parts)

    if corr is not None and best is not None:
        days = min(len(best[0].daily_returns), len(best[1].daily_returns))
        evidence.append(
            f"用最近 {days} 个交易日的日涨跌算的。接近 1 表示几乎同涨同跌，接近 0 表示各走各的。"
        )
    if residual is not None and corr is not None:
        extra = (
            "一起动主要是跟着大盘，不是这两个行业绑在一起。"
            if residual < 0.2
            else ""
        )
        evidence.append(
            f"这两只相关大约 {corr:.2f}。去掉沪深300当天涨跌之后大约 {residual:.2f}。{extra}"
        )
    if all_theme and len(labels) >= 2:
        evidence.append(
            f"再买{labels[1]}，是在加另一个行业，不是在加{labels[0]}。"
        )

    return Judgment(title=title, evidence=evidence, level="info", kind="现状")


def look_one(
    candidate: PositionSnapshot,
    holdings: list[PositionSnapshot],
    market: MarketSnapshot | None = None,
) -> Judgment:
    if candidate.price is None:
        return Judgment(
            title="暂时没有行情，无法判断现在贵不贵",
            evidence=[f"{candidate.code} 没有现价，行情没查到或连不上"],
            level="watch",
            kind="现状",
        )

    parts: list[str] = []
    quote_word = _quote_word(candidate)
    evidence: list[str] = [
        f"{candidate.name}（{candidate.code}）{quote_word} {candidate.price:.4f}"
    ]
    held_codes = {p.code.strip() for p in holdings}
    already = candidate.code.strip() in held_codes
    if already:
        parts.append("这只你已经有了")

    heaviest: PositionSnapshot | None = None
    heaviest_v = -1.0
    total = 0.0
    for p in holdings:
        v = _market_value(p)
        if v:
            total += v
            if v > heaviest_v:
                heaviest_v = v
                heaviest = p

    stock = [p for p in holdings if _bucket(p) == "股票"]
    stock_labels: list[str] = []
    for p in stock:
        lab = _theme_label(p.name)
        if lab and lab not in stock_labels:
            stock_labels.append(lab)
    held_all_theme = bool(stock) and not any(
        any(b in p.name for b in _BROAD) for p in stock
    )
    cand_bucket = _bucket(candidate)
    cand_label = _theme_label(candidate.name)
    broad = any(b in candidate.name for b in _BROAD)
    heavy_lab = (
        _theme_label(heaviest.name) if heaviest else None
    ) or (heaviest.name if heaviest else "")

    if cand_bucket == "货币":
        parts.append("这只是货币，不是股票")
    elif cand_bucket == "债券":
        parts.append("这只是债券")
    elif broad:
        names = "、".join(stock_labels) if stock_labels else "行业基金"
        parts.append(f"这只是{cand_label or '沪深300'}，比你手里的{names}更散")
    elif cand_label:
        parts.append(f"这只是{cand_label}")
        if not already and heaviest:
            same = cand_label == heavy_lab or cand_label in heavy_lab or heavy_lab in cand_label
            if same:
                parts.append(f"和手里已经最重的{heavy_lab}是同一类行业")
            else:
                parts.append("和手里这些不是同一类行业")
                evidence.append(f"再买是开另一个行业，不是在加{heavy_lab}。")
    elif held_all_theme and not already:
        parts.append("和手里这些不一定是同一类")

    range_title, range_pct = _range_place(candidate)
    if range_title:
        parts.append(range_title)
        evidence.append(
            f"这段行情最低 {candidate.low_120:.4f}、最高 {candidate.high_120:.4f}，现价在其中 {range_pct:.0%} 的位置"
        )
    vs_title, vs_evi = _vs_hs300(candidate, market)
    if vs_title:
        parts.append(vs_title)
        if vs_evi:
            evidence.append(vs_evi)
    if candidate.quantity and candidate.price and total:
        add_v = candidate.quantity * candidate.price
        evidence.append(
            f"按这个数量，市值 {add_v:.2f} 元，加进去后约占全部 {add_v / (total + add_v):.0%}"
        )
        mix_title, _mix_evi = _mix_title(list(holdings) + [candidate])
        if mix_title:
            evidence.append("按这个数量加进去后：" + mix_title)
    if heaviest and candidate.daily_returns and heaviest.daily_returns:
        corr = _pair_corr(candidate.daily_returns, heaviest.daily_returns)
        if corr is not None:
            evidence.append(
                f"和手里最重的{heaviest.name}最近涨跌相关大约 {corr:.2f}"
            )
    if candidate.top_holdings:
        asof = f"（截至 {candidate.holdings_asof}）" if candidate.holdings_asof else ""
        evidence.append(
            "主要持仓"
            + asof
            + "："
            + "、".join(candidate.top_holdings[:8])
        )
    elif candidate.kind == "基金":
        evidence.append("主要持仓这次没查到。")
    if candidate.announcements:
        evidence.append("最近有公告，先读完再决定加不加。")
        evidence.extend(candidate.announcements)

    title = "。".join(parts) + "。" if parts else "有行情，但还拼不出和手里这些的关系。"
    return Judgment(title=title, evidence=evidence, level="info", kind="现状")


def judge_all(
    positions: list[PositionSnapshot],
    market: MarketSnapshot | None = None,
    cash=None,
) -> Report:
    values = [_market_value(p) for p in positions]
    total_value = sum(v for v in values if v is not None)
    total_cost = sum(p.quantity * p.cost for p in positions)

    judged: list[PositionJudgment] = []
    for pos in positions:
        judged.append(
            PositionJudgment(
                snapshot=pos,
                items=judge_one(pos, total_value if total_value else None, market),
                market_value=_market_value(pos),
                pnl_pct=_pnl_pct(pos),
            )
        )

    any_alert = any(j.kind != "现状" for p in judged for j in p.items)
    pnl_amount = total_value - total_cost
    pnl_pct = (pnl_amount / total_cost) if total_cost else 0.0
    max_share = 0.0
    max_name = ""
    if total_value:
        for p in judged:
            if p.market_value:
                share = p.market_value / total_value
                if share > max_share:
                    max_share = share
                    max_name = p.snapshot.name

    if pnl_pct <= -0.03:
        title = f"相对成本亏 {abs(pnl_pct):.1%}"
    elif pnl_pct >= 0.03:
        title = f"相对成本赚 {pnl_pct:.1%}"
    else:
        title = "相对成本和现价差不多"
    if max_name and len(judged) > 1:
        title += f"。钱主要在{max_name}（约 {max_share:.0%}）"
    title += "。"
    if any_alert:
        title = title.rstrip("。") + "。下面几条需要看一眼。"

    evidence = [
        f"总市值 {total_value:.2f} 元",
        f"总成本 {total_cost:.2f} 元",
        f"相对成本 {pnl_pct:.1%}",
    ]
    if max_name:
        evidence.append(f"最重的一只是 {max_name}，约占 {max_share:.0%}")
    place_value: dict[str, float] = {}
    for p in judged:
        if p.market_value:
            name = _place_of(p.snapshot)
            place_value[name] = place_value.get(name, 0) + p.market_value
    place_total = sum(place_value.values())
    if place_total:
        bits = [
            f"{name}约 {val / place_total:.0%}" for name, val in place_value.items()
        ]
        evidence.append("按市值：" + "，".join(bits) + "。这里只算已经填进来的。")
    if "支付宝" not in place_value:
        evidence.append("支付宝买的基金要自己加上，才会算进总市值和判断。")

    cash_total = 0.0
    cash_known = False
    if cash is not None:
        cash_known = bool(getattr(cash, "known", False) or getattr(cash, "updated_at", ""))
        cash_total = float(getattr(cash, "total", 0) or 0)
    if cash_known:
        yj = float(getattr(cash, "yongjinbao", 0) or 0)
        ap = float(getattr(cash, "alipay", 0) or 0)
        evidence.append(
            f"可用现金合计 {cash_total:.2f} 元（佣金宝 {yj:.2f}，支付宝 {ap:.2f}）。手填的，不是券商实时余额。"
        )
        wealth = total_value + cash_total
        if wealth > 0:
            cash_share = cash_total / wealth
            evidence.append(f"现金约占「持仓市值+现金」的 {cash_share:.0%}")
            if cash_share < 0.08 and total_value > 0:
                title = title.rstrip("。") + "。现金偏少。"
            elif cash_share >= 0.25:
                title = title.rstrip("。") + "。现金还算有余量。"
    else:
        evidence.append("可用现金还没填。填了之后，加仓/减仓的判断会更靠谱。")

    overall = Judgment(
        title=title,
        evidence=evidence,
        level="watch" if any_alert or pnl_pct <= -0.1 else "info",
        kind="现状",
    )

    return Report(
        overall=overall,
        positions=judged,
        total_value=total_value,
        total_cost=total_cost,
        market=market,
        market_judgment=_market_judgment(judged, market) if market else None,
        structure_judgment=_structure_judgment(positions, market),
    )
