import pandas as pd

from holdings.plan import build_plan


def _df(closes, vols=None, ma5=None, ma20=None, ma60=None):
    n = len(closes)
    vols = vols or [100.0] * n
    row = {
        "close": closes,
        "low": [c * 0.98 for c in closes],
        "vol": vols,
        "ma5": [ma5 or closes[-1]] * n,
        "ma20": [ma20 or closes[-1]] * n,
        "ma60": [ma60 or closes[-1]] * n,
    }
    return pd.DataFrame(row)


def _fx(val, date, done=True, kind="di"):
    return {"index": 0, "type": kind, "val": val, "date": date, "done": done}


def test_defenses_sorted_near_to_far_with_labels():
    df = _df([1.10] * 30, ma5=1.12, ma20=1.02, ma60=0.95)
    fractals = [_fx(0.987, "2026-07-24"), _fx(1.027, "2026-08-14")]
    plan = build_plan(df, fractals)
    assert plan.has
    levels = [d.level for d in plan.defenses]
    assert levels == sorted(levels, reverse=True)
    labels = [d.label for d in plan.defenses]
    assert "8-14 底" in labels and "MA20" in labels and "7-24 底" in labels
    assert levels[0] == 1.027


def test_near_duplicate_levels_merged():
    df = _df([1.10] * 30, ma5=1.12, ma20=1.024, ma60=0.9)
    fractals = [_fx(1.027, "2026-08-14")]
    plan = build_plan(df, fractals)
    near = [d for d in plan.defenses if abs(d.level - 1.027) / 1.027 < 0.01]
    assert len(near) == 1
    assert near[0].label == "8-14 底"


def test_fractal_above_price_and_unconfirmed_skipped():
    df = _df([1.10] * 30, ma5=1.12, ma20=1.02, ma60=0.9)
    fractals = [
        _fx(1.20, "2026-08-18"),
        _fx(0.99, "2026-08-19", done=False),
        _fx(1.027, "2026-08-14"),
        _fx(1.05, "2026-08-13", kind="ding"),
    ]
    plan = build_plan(df, fractals)
    labels = [d.label for d in plan.defenses]
    assert "8-14 底" in labels
    assert all(d.level < 1.10 for d in plan.defenses)
    assert "8-19 底" not in labels and "8-13 底" not in labels


def test_heavy_down_day_adds_no_add_principle():
    closes = [1.10] * 29 + [1.017]
    vols = [100.0] * 29 + [160.0]
    df = _df(closes, vols=vols, ma5=1.07, ma20=1.00, ma60=0.95)
    plan = build_plan(df, [_fx(0.99, "2026-08-14")])
    blob = "".join(plan.principles)
    assert "默认不是加仓日" in blob
    assert "缩量企稳" in blob


def test_quiet_down_day_no_no_add_line():
    closes = [1.10] * 29 + [1.09]
    df = _df(closes, ma5=1.11, ma20=1.05, ma60=1.00)
    plan = build_plan(df, [_fx(1.02, "2026-08-14")])
    assert all("加仓日" not in p for p in plan.principles)


def test_loss_over_5pct_warns_against_averaging_down():
    df = _df([1.0] * 30, ma5=1.05, ma20=0.98, ma60=0.9)
    plan = build_plan(df, [_fx(0.96, "2026-08-14")], cost=1.09)
    assert any("摊低成本" in p for p in plan.principles)


def test_heavy_position_principle():
    df = _df([1.0] * 30, ma5=1.05, ma20=0.98, ma60=0.9)
    plan = build_plan(df, [_fx(0.96, "2026-08-14")], book_value=40000, cash_total=17000)
    assert any("仓位约" in p and "偏重" in p for p in plan.principles)


def test_confirm_depends_on_ma5_side():
    below = build_plan(_df([1.0] * 30, ma5=1.06, ma20=0.98, ma60=0.9), [_fx(0.96, "2026-08-14")])
    assert "收复 MA5" in below.confirm and "反抽" in below.confirm
    above = build_plan(_df([1.07] * 30, ma5=1.06, ma20=0.98, ma60=0.9), [_fx(0.96, "2026-08-14")])
    assert "上方" in above.confirm


def test_scenarios_reference_first_two_defenses():
    df = _df([1.041] * 30, ma5=1.07, ma20=1.0198, ma60=0.93)
    fractals = [_fx(1.027, "2026-08-14"), _fx(0.987, "2026-07-24")]
    plan = build_plan(df, fractals)
    cases = [s.case for s in plan.scenarios]
    actions = [s.action for s in plan.scenarios]
    assert any("收复 MA5" in c for c in cases)
    assert any("缩量企稳" in c for c in cases)
    assert any("放量跌破 1.027" in c for c in cases)
    assert any("下看 1.020" in a for a in actions)
    assert any("横盘" in c for c in cases)
    assert any("认错" in a for a in actions)


def test_no_fractals_falls_back_to_ma_lines():
    df = _df([1.10] * 30, ma5=1.12, ma20=1.02, ma60=0.95)
    plan = build_plan(df, None)
    assert plan.has
    assert [d.label for d in plan.defenses] == ["MA20", "MA60"]


def test_nothing_below_price_falls_back_to_recent_low():
    df = _df([0.90] * 30, ma5=0.89, ma20=0.92, ma60=0.95)
    plan = build_plan(df, [_fx(0.93, "2026-08-14")])
    assert plan.has
    assert plan.defenses[0].label == "近 20 日最低"
    assert plan.defenses[0].level < 0.90


def test_empty_df_no_plan():
    assert not build_plan(None).has
    assert not build_plan(pd.DataFrame()).has


def test_ma_computed_from_close_when_columns_missing():
    closes = [1.00] * 55 + [1.10] * 5  # MA5=1.10, MA20=1.025, MA60≈1.008
    df = pd.DataFrame({"close": closes, "low": [c * 0.98 for c in closes], "vol": [100.0] * 60})
    plan = build_plan(df, [_fx(0.98, "2026-08-14")])
    assert plan.has
    labels = [d.label for d in plan.defenses]
    assert "MA20" in labels
    ma20 = next(d for d in plan.defenses if d.label == "MA20")
    assert abs(ma20.level - 1.025) < 1e-3
    assert "上方" in plan.confirm  # 现价 1.10 == MA5
