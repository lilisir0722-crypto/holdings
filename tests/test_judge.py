from holdings.judge import PositionSnapshot, judge_all, judge_one


def test_no_price_says_cannot_judge():
    pos = PositionSnapshot(
        code="600519",
        name="贵州茅台",
        kind="股票",
        quantity=100,
        cost=1500.0,
        price=None,
    )
    items = judge_one(pos, total_value=None)
    assert any("没有行情" in i.title for i in items)
    assert items[0].evidence


def test_heavy_weight_when_over_thirty_percent():
    pos = PositionSnapshot(
        code="600519",
        name="贵州茅台",
        kind="股票",
        quantity=100,
        cost=1500.0,
        price=1800.0,
    )
    items = judge_one(pos, total_value=200_000)
    titles = [i.title for i in items]
    assert any("占比偏高" in t for t in titles)
    heavy = next(i for i in items if "占比偏高" in i.title)
    assert any("90" in e or "90%" in e for e in heavy.evidence)


def test_loss_over_twenty_percent():
    pos = PositionSnapshot(
        code="000001",
        name="平安银行",
        kind="股票",
        quantity=1000,
        cost=12.0,
        price=9.0,
    )
    items = judge_one(pos, total_value=9000)
    assert any("亏得比较多" in i.title for i in items)


def test_gain_over_fifty_percent():
    pos = PositionSnapshot(
        code="000001",
        name="平安银行",
        kind="股票",
        quantity=1000,
        cost=10.0,
        price=16.0,
    )
    items = judge_one(pos, total_value=16_000)
    assert any("赚得比较多" in i.title for i in items)


def test_near_120d_high():
    pos = PositionSnapshot(
        code="510300",
        name="沪深300ETF",
        kind="股票",
        quantity=1000,
        cost=4.0,
        price=4.95,
        high_120=5.0,
        low_120=3.5,
    )
    items = judge_one(pos, total_value=4950)
    assert any("高位" in i.title for i in items)


def test_near_120d_low():
    pos = PositionSnapshot(
        code="510300",
        name="沪深300ETF",
        kind="股票",
        quantity=1000,
        cost=4.0,
        price=3.52,
        high_120=5.0,
        low_120=3.5,
    )
    items = judge_one(pos, total_value=3520)
    assert any("低位" in i.title for i in items)


def test_recent_announcement():
    pos = PositionSnapshot(
        code="600519",
        name="贵州茅台",
        kind="股票",
        quantity=10,
        cost=1500.0,
        price=1500.0,
        announcements=["2026-08-10 股东大会决议公告"],
    )
    items = judge_one(pos, total_value=15_000)
    hit = next(i for i in items if "公告" in i.title)
    assert "先读" in hit.title
    assert any("股东大会" in e for e in hit.evidence)


def test_always_writes_situation_even_for_small_loss():
    pos = PositionSnapshot(
        code="562590",
        name="半导体设备ETF华夏",
        kind="基金",
        quantity=17200,
        cost=1.1424,
        price=1.05,
        high_120=1.26,
        low_120=0.85,
        change_20d_pct=0.06,
    )
    items = judge_one(pos, total_value=26_000)
    sit = next(i for i in items if i.kind == "现状")
    assert "相对成本亏" in sit.title
    assert any("1.14" in e or "1.1424" in e for e in sit.evidence)
    assert any("这段行情" in e or "0.85" in e for e in sit.evidence)
    assert any("再买同样数量" in e for e in sit.evidence)


def test_holding_weaker_than_hs300():
    from holdings.judge import MarketSnapshot

    pos = PositionSnapshot(
        code="562590",
        name="半导体设备ETF华夏",
        kind="基金",
        quantity=17200,
        cost=1.1424,
        price=1.05,
        high_120=1.26,
        low_120=0.85,
        change_20d_pct=-0.10,
    )
    hs300 = MarketSnapshot(
        code="510300",
        name="沪深300",
        price=4.5,
        day_change_pct=0.005,
        change_20d_pct=0.02,
    )
    items = judge_one(pos, total_value=26_000, market=hs300)
    sit = next(i for i in items if i.kind == "现状")
    assert "沪深300" in sit.title
    assert "弱" in sit.title
    assert any("沪深300" in e for e in sit.evidence)


def test_overall_includes_hs300():
    from holdings.judge import MarketSnapshot

    a = PositionSnapshot(
        code="562590",
        name="半导体设备ETF华夏",
        kind="基金",
        quantity=17200,
        cost=1.1424,
        price=1.05,
        high_120=1.26,
        low_120=0.85,
        change_20d_pct=-0.08,
    )
    b = PositionSnapshot(
        code="159530",
        name="机器人ETF易方达",
        kind="基金",
        quantity=5900,
        cost=1.4634,
        price=1.398,
        high_120=1.80,
        low_120=1.24,
        change_20d_pct=-0.04,
    )
    hs300 = MarketSnapshot(
        code="510300",
        name="沪深300",
        price=4.5,
        change_20d_pct=0.01,
    )
    report = judge_all([a, b], market=hs300)
    assert report.market_judgment is not None
    assert "沪深300" in report.market_judgment.title


def test_two_funds_overall_says_where_money_is():
    a = PositionSnapshot(
        code="562590",
        name="半导体设备ETF华夏",
        kind="基金",
        quantity=17200,
        cost=1.1424,
        price=1.05,
        high_120=1.26,
        low_120=0.85,
    )
    b = PositionSnapshot(
        code="159530",
        name="机器人ETF易方达",
        kind="基金",
        quantity=5900,
        cost=1.4634,
        price=1.398,
        high_120=1.80,
        low_120=1.24,
    )
    report = judge_all([a, b])
    assert "相对成本亏" in report.overall.title
    assert "半导体" in report.overall.title
    assert any("已经填进来" in e or "支付宝" in e for e in report.overall.evidence)


def test_overall_uses_sum_of_market_value():
    a = PositionSnapshot(
        code="600519",
        name="贵州茅台",
        kind="股票",
        quantity=10,
        cost=1500.0,
        price=1600.0,
        high_120=2000.0,
        low_120=1000.0,
    )
    b = PositionSnapshot(
        code="510300",
        name="沪深300ETF",
        kind="股票",
        quantity=1000,
        cost=4.0,
        price=4.0,
        high_120=5.0,
        low_120=3.0,
    )
    report = judge_all([a, b])
    assert report.total_value == 20_000.0
    assert any("20000" in e or "20,000" in e or "20,000.00" in e or "20000.00" in e for e in report.overall.evidence)


def _returns(pattern: list[float], times: int = 8) -> list[float]:
    return pattern * times


def test_two_theme_funds_that_move_together():
    same = _returns([0.01, -0.02, 0.015, -0.01, 0.008])
    a = PositionSnapshot(
        code="562590",
        name="半导体设备ETF华夏",
        kind="基金",
        quantity=17200,
        cost=1.1424,
        price=1.05,
        daily_returns=same,
        place="佣金宝",
    )
    b = PositionSnapshot(
        code="159530",
        name="机器人ETF易方达",
        kind="基金",
        quantity=5900,
        cost=1.4634,
        price=1.398,
        daily_returns=same,
        place="佣金宝",
    )
    report = judge_all([a, b])
    assert report.structure_judgment is not None
    title = report.structure_judgment.title
    assert "半导体" in title
    assert "机器人" in title
    assert "行业不同" in title
    assert "一起动" in title
    assert any("1.00" in title or "1.0" in e for e in [title, *report.structure_judgment.evidence])
    assert any("另一个行业" in e for e in report.structure_judgment.evidence)
    assert not any("同一类" in e for e in report.structure_judgment.evidence)
    assert "股票" in title
    assert any("支付宝" in e or "已经填进来" in e for e in report.overall.evidence)


def test_two_industry_etfs_are_almost_all_stock():
    a = PositionSnapshot(
        code="562590",
        name="半导体设备ETF华夏",
        kind="基金",
        quantity=17200,
        cost=1.1424,
        price=1.05,
        place="佣金宝",
    )
    b = PositionSnapshot(
        code="159530",
        name="机器人ETF易方达",
        kind="基金",
        quantity=5900,
        cost=1.4634,
        price=1.398,
        place="佣金宝",
    )
    report = judge_all([a, b])
    title = report.structure_judgment.title
    assert "股票" in title
    assert "债券" in title or "货币" in title
    blob = " ".join(report.structure_judgment.evidence + report.overall.evidence)
    assert "佣金宝" in blob


def test_money_market_shows_stock_and_cash_share():
    a = PositionSnapshot(
        code="562590",
        name="半导体设备ETF华夏",
        kind="基金",
        quantity=17200,
        cost=1.1424,
        price=1.05,
        place="佣金宝",
    )
    b = PositionSnapshot(
        code="000198",
        name="天弘余额宝货币",
        kind="基金",
        quantity=1000,
        cost=1.0,
        price=1.0,
        place="支付宝",
    )
    report = judge_all([a, b])
    title = report.structure_judgment.title
    assert "股票" in title
    assert "货币" in title
    blob = " ".join(report.overall.evidence)
    assert "佣金宝" in blob
    assert "支付宝" in blob
    assert any("%" in e and "佣金宝" in e for e in report.overall.evidence)


def test_co_move_mostly_follows_hs300():
    from holdings.judge import MarketSnapshot

    m = _returns([0.01, -0.012, 0.008, 0.003, -0.006])
    extra_a = _returns([0.02, -0.02, 0.01, -0.01, 0.00])
    extra_b = _returns([-0.015, 0.01, 0.02, -0.005, 0.005])
    a = PositionSnapshot(
        code="562590",
        name="半导体设备ETF华夏",
        kind="基金",
        quantity=17200,
        cost=1.1424,
        price=1.05,
        daily_returns=[x + y for x, y in zip(m, extra_a)],
        place="佣金宝",
    )
    b = PositionSnapshot(
        code="159530",
        name="机器人ETF易方达",
        kind="基金",
        quantity=5900,
        cost=1.4634,
        price=1.398,
        daily_returns=[x + y for x, y in zip(m, extra_b)],
        place="佣金宝",
    )
    hs300 = MarketSnapshot(
        code="510300",
        name="沪深300",
        price=4.5,
        change_20d_pct=0.01,
        daily_returns=m,
    )
    report = judge_all([a, b], market=hs300)
    assert "跟着大盘" in report.structure_judgment.title
    assert any("沪深300" in e for e in report.structure_judgment.evidence)


def test_alipay_and_commission_are_counted_separately():
    a = PositionSnapshot(
        code="562590",
        name="半导体设备ETF华夏",
        kind="基金",
        quantity=17200,
        cost=1.1424,
        price=1.05,
        place="佣金宝",
    )
    b = PositionSnapshot(
        code="000198",
        name="天弘余额宝货币",
        kind="基金",
        quantity=1000,
        cost=1.0,
        price=1.0,
        place="支付宝",
    )
    report = judge_all([a, b])
    blob = " ".join(report.overall.evidence)
    assert "佣金宝" in blob
    assert "支付宝" in blob
    assert any("%" in e and ("佣金宝" in e or "支付宝" in e) for e in report.overall.evidence)


def test_overall_mentions_cash_when_filled():
    from holdings.store import CashBook

    a = PositionSnapshot(
        code="562590",
        name="半导体设备ETF华夏",
        kind="基金",
        quantity=17200,
        cost=1.1424,
        price=1.05,
        place="佣金宝",
    )
    cash = CashBook(yongjinbao=3000, alipay=1000, updated_at="2026-08-16")
    report = judge_all([a], cash=cash)
    blob = " ".join(report.overall.evidence)
    assert "可用现金" in blob
    assert "3000" in blob or "4000" in blob
    assert "现金" in report.overall.title or "现金" in blob


def test_overall_reminds_to_fill_cash_when_unknown():
    a = PositionSnapshot(
        code="562590",
        name="半导体设备ETF华夏",
        kind="基金",
        quantity=17200,
        cost=1.1424,
        price=1.05,
    )
    report = judge_all([a])
    assert any("可用现金" in e and "填" in e for e in report.overall.evidence)


def test_two_funds_that_do_not_move_together():
    up = _returns([0.01, 0.02, -0.01, 0.015, 0.005])
    down = [-x for x in up]
    a = PositionSnapshot(
        code="562590",
        name="半导体设备ETF华夏",
        kind="基金",
        quantity=17200,
        cost=1.1424,
        price=1.05,
        daily_returns=up,
    )
    b = PositionSnapshot(
        code="511010",
        name="国债ETF",
        kind="基金",
        quantity=10000,
        cost=1.0,
        price=1.0,
        daily_returns=down,
    )
    report = judge_all([a, b])
    assert report.structure_judgment is not None
    assert "不太一起动" in report.structure_judgment.title


def test_one_holding_still_says_what_the_money_is_in():
    a = PositionSnapshot(
        code="510300",
        name="沪深300ETF",
        kind="股票",
        quantity=1000,
        cost=4.0,
        price=4.0,
        daily_returns=_returns([0.01, -0.01, 0.02, 0.0, -0.005]),
    )
    report = judge_all([a])
    assert report.structure_judgment is not None
    assert "股票" in report.structure_judgment.title


def _held_semi_robot():
    a = PositionSnapshot(
        code="562590",
        name="半导体设备ETF华夏",
        kind="基金",
        quantity=17200,
        cost=1.1424,
        price=1.05,
        place="佣金宝",
    )
    b = PositionSnapshot(
        code="159530",
        name="机器人ETF易方达",
        kind="基金",
        quantity=5900,
        cost=1.4634,
        price=1.398,
        place="佣金宝",
    )
    return [a, b]


def test_look_already_held():
    from holdings.judge import look_one

    held = _held_semi_robot()
    cand = PositionSnapshot(
        code="562590",
        name="半导体设备ETF华夏",
        kind="基金",
        quantity=0,
        cost=0,
        price=1.05,
        high_120=1.26,
        low_120=0.85,
    )
    hit = look_one(cand, held)
    assert "已经有了" in hit.title


def test_look_hs300_is_broader_than_industry_holdings():
    from holdings.judge import look_one

    cand = PositionSnapshot(
        code="510300",
        name="沪深300ETF",
        kind="股票",
        quantity=0,
        cost=0,
        price=4.7,
        high_120=5.1,
        low_120=4.4,
        change_20d_pct=0.03,
    )
    hit = look_one(cand, _held_semi_robot())
    assert "更散" in hit.title
    assert "沪深300" in hit.title


def test_look_other_industry_is_not_adding_semiconductor():
    from holdings.judge import look_one

    cand = PositionSnapshot(
        code="159992",
        name="创新药ETF",
        kind="基金",
        quantity=0,
        cost=0,
        price=1.2,
        high_120=1.5,
        low_120=1.0,
    )
    hit = look_one(cand, _held_semi_robot())
    assert "创新药" in hit.title
    assert any("另一个行业" in e or "不是在加半导体" in e for e in hit.evidence)


def test_look_no_price():
    from holdings.judge import look_one

    cand = PositionSnapshot(
        code="999999",
        name="没有",
        kind="股票",
        quantity=0,
        cost=0,
        price=None,
    )
    hit = look_one(cand, _held_semi_robot())
    assert "没有行情" in hit.title


def test_look_otc_fund_says_net_value():
    from holdings.judge import look_one

    cand = PositionSnapshot(
        code="000198",
        name="天弘余额宝货币",
        kind="基金",
        quantity=0,
        cost=0,
        price=1.0,
        place="支付宝",
    )
    hit = look_one(cand, _held_semi_robot())
    blob = hit.title + " " + " ".join(hit.evidence)
    assert "净值" in blob
    assert "现价" not in blob


def test_look_lists_top_holdings():
    from holdings.judge import look_one

    cand = PositionSnapshot(
        code="562590",
        name="半导体设备ETF华夏",
        kind="基金",
        quantity=0,
        cost=0,
        price=1.05,
        top_holdings=["北方华创", "中微公司", "盛美上海"],
    )
    hit = look_one(cand, _held_semi_robot())
    blob = " ".join(hit.evidence)
    assert "北方华创" in blob
    assert "中微公司" in blob


def test_look_adding_cash_changes_mix():
    from holdings.judge import look_one

    cand = PositionSnapshot(
        code="000198",
        name="天弘余额宝货币",
        kind="基金",
        quantity=20000,
        cost=0,
        price=1.0,
    )
    hit = look_one(cand, _held_semi_robot())
    blob = " ".join(hit.evidence)
    assert "货币" in blob
    assert "加进去" in blob
    assert "股票" in blob


def test_look_announcements_ask_to_read():
    from holdings.judge import look_one

    cand = PositionSnapshot(
        code="510300",
        name="沪深300ETF",
        kind="股票",
        quantity=0,
        cost=0,
        price=4.7,
        announcements=["2026-08-10 基金份额折算公告"],
    )
    hit = look_one(cand, _held_semi_robot())
    assert any("先读" in e for e in hit.evidence)
    assert any("折算" in e for e in hit.evidence)
