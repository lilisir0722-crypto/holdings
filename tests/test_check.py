from holdings.check import check_trade, locate
from holdings.plan import PlanLevel, PlanView


def _plan(*, price=1.041, ma5=1.073, defenses=None, principles=None) -> PlanView:
    ds = defenses or [
        PlanLevel(1.027, "8-14 底"),
        PlanLevel(1.02, "MA20"),
        PlanLevel(0.987, "7-24 底"),
    ]
    return PlanView(
        has=True,
        price=price,
        ma5=ma5,
        defenses=ds,
        principles=list(principles or []),
        confirm="收复 MA5 才算右侧确认",
    )


def test_locate_gap_between_defense_and_ma5():
    plan = _plan()
    assert locate(1.03, plan) == "gap"
    assert locate(1.025, plan) == "defense"
    assert locate(1.08, plan) == "right"
    assert locate(1.010, plan) == "below"


def test_buy_in_the_gap_is_against_plan():
    out = check_trade(side="买", price=1.03, qty=5000, plan=_plan())
    assert out.verdict == "不符合"
    blob = "".join(out.reasons)
    assert "两头不靠" in blob
    assert "1.027" in blob and "1.073" in blob


def test_buy_in_defense_band_ok():
    out = check_trade(side="买", price=1.023, qty=1000, plan=_plan(), cash=20000)
    assert out.verdict == "符合"
    assert "防线一带" in "".join(out.reasons)


def test_buy_above_ma5_is_right_side():
    out = check_trade(side="买", price=1.08, qty=1000, plan=_plan(), cash=20000)
    assert out.verdict == "符合"
    assert "右侧确认" in "".join(out.reasons)


def test_buy_on_heavy_drop_day_blocked_unless_defense():
    p = _plan(principles=["刚收一根放量大阴线，次日默认不是加仓日；除非首道防线附近出现明确的缩量企稳。"])
    gap = check_trade(side="买", price=1.03, qty=1000, plan=p, cash=20000)
    assert gap.verdict == "不符合"
    assert "不是加仓日" in "".join(gap.reasons)
    band = check_trade(side="买", price=1.023, qty=1000, plan=p, cash=20000)
    assert band.verdict == "部分符合"
    assert "缩量企稳" in "".join(band.reasons)


def test_buy_cash_short_and_not_small():
    short = check_trade(side="买", price=1.023, qty=20000, plan=_plan(), cash=5000)
    assert short.verdict == "不符合"
    assert "现金" in "".join(short.reasons)
    fat = check_trade(side="买", price=1.023, qty=9000, plan=_plan(), cash=20000)
    assert fat.verdict == "部分符合"
    assert "小仓" in "".join(fat.reasons)


def test_buy_averaging_and_heavy_are_warnings():
    p = _plan(principles=["相对成本 1.1424 已浮亏约 8.9%，别为了摊低成本而加仓。", "整体仓位约 70%，偏重；先把“不动”当默认动作。"])
    out = check_trade(side="买", price=1.023, qty=500, plan=p, cash=20000, cost=1.1424)
    assert out.verdict == "部分符合"
    blob = "".join(out.reasons)
    assert "摊低成本" in blob and "偏重" in blob


def test_sell_below_defense_ok():
    out = check_trade(side="卖", price=1.01, qty=1000, plan=_plan(), hold_qty=17200)
    assert out.verdict == "符合"
    assert "防线" in "".join(out.reasons)


def test_sell_above_ma5_is_early():
    out = check_trade(side="卖", price=1.08, qty=1000, plan=_plan(), hold_qty=17200)
    assert out.verdict == "部分符合"
    assert "提前降仓" in "".join(out.reasons)


def test_sell_qty_mismatch_warns():
    out = check_trade(side="卖", price=1.01, qty=99999, plan=_plan(), hold_qty=100)
    assert out.verdict == "部分符合"
    assert "数量对不上" in "".join(out.reasons)


def test_no_plan_and_bad_input():
    empty = PlanView()
    out = check_trade(side="买", price=1.03, qty=1000, plan=empty)
    assert out.verdict == "没法对照"
    bad = check_trade(side="买", price=0, qty=1000, plan=_plan())
    assert bad.verdict == "没法对照"


def test_buy_against_last_watch_snapshot():
    journals = [
        {
            "date": "2026-08-20",
            "price": 1.041,
            "stance": "指标说法不一致，更宜观望。",
            "later": {"5d": {"chg_pct": -4.1}},
        }
    ]
    out = check_trade(side="买", price=1.023, qty=500, plan=_plan(), cash=20000, journals=journals)
    assert out.verdict == "部分符合"
    assert "对着干" in out.past
    assert "-4.1%" in out.past
