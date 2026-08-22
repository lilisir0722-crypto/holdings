import pandas as pd

from holdings.tech import BoardBlock, InfoBlock, UnusualBlock, summarize_main_intent


def _days(mains, smalls=None, start=10, close0=1.10, close_step=0.0, closes=None, vols=None):
    smalls = smalls if smalls is not None else [0.0] * len(mains)
    cap = pd.DataFrame(
        [
            {
                "date": f"2026-08-{start + i:02d}",
                "main_net": mains[i],
                "small_net": smalls[i],
            }
            for i in range(len(mains))
        ]
    )
    if closes is None:
        closes = [close0 + i * close_step for i in range(len(mains))]
    rows = [
        {"date": f"2026-08-{start + i:02d}", "close": closes[i]}
        for i in range(len(mains))
    ]
    if vols is not None:
        for i, row in enumerate(rows):
            row["amount"] = vols[i]
    daily = pd.DataFrame(rows)
    return cap, daily


def test_intent_empty_is_unclear():
    block = summarize_main_intent(None, None)
    assert not block.ok
    assert "看不清" in block.title
    assert "立即买入" not in block.title
    assert any("大单" in e or "不是账户" in e for e in block.evidence)


def test_intent_inflow_while_price_drops_reads_as_absorb():
    cap, daily = _days([2e7] * 5, close0=1.10, close_step=-0.015)
    block = summarize_main_intent(cap, daily)
    assert block.ok
    assert "吸筹" in block.title
    assert any("净流入" in e for e in block.evidence)
    assert any("2026-08-" in e for e in block.evidence)


def test_intent_outflow_while_price_rises_reads_as_distribute():
    cap, daily = _days([-2e7] * 5, close0=1.00, close_step=0.015)
    block = summarize_main_intent(cap, daily)
    assert block.ok
    assert "派发" in block.title


def test_intent_inflow_with_rising_price_reads_as_follow():
    cap, daily = _days([2e7] * 5, close0=1.00, close_step=0.015)
    block = summarize_main_intent(cap, daily)
    assert block.ok
    assert "加仓" in block.title or "顺势" in block.title or "拉升" in block.title


def test_intent_mixed_days_is_unclear():
    cap, daily = _days([2e7, -2e7, 1e7, -3e7, 5e6], close0=1.05, close_step=0.0)
    block = summarize_main_intent(cap, daily)
    assert "看不清" in block.title or "不齐" in block.title
    assert "保证" not in block.title


def test_intent_includes_board_and_etf_when_given():
    cap, daily = _days([2e7] * 5, close0=1.10, close_step=-0.01)
    boards = [
        BoardBlock(
            title="半导体（880001）",
            evidence=["主力净流入 -2.00 亿"],
            ok=True,
            summary_line="所属板块 半导体 主力净流入为负",
        )
    ]
    etf = InfoBlock(title="份额在增加", evidence=["近 5 日份额上行"], ok=True)
    unusual = UnusualBlock(title="异动名单里有这只，共 1 条", evidence=["大笔买入"], ok=True)
    block = summarize_main_intent(cap, daily, boards=boards, etf=etf, unusual=unusual)
    blob = block.title + "".join(block.evidence)
    assert "半导体" in blob
    assert "份额" in blob
    assert "异动" in blob


def test_intent_volume_spike_then_fade_reads_as_probe():
    cap, daily = _days(
        [1e6, 1e6, 2e6, 3e7, 3e6],
        closes=[1.00, 1.002, 1.001, 1.028, 1.010],
        vols=[1e8, 1.1e8, 9e7, 3.2e8, 8e7],
    )
    block = summarize_main_intent(cap, daily)
    assert block.ok
    assert "试盘" in block.title
    assert any("放量" in e or "缩量" in e for e in block.evidence)


def test_intent_dip_then_reclaim_with_inflow_reads_as_wash():
    cap, daily = _days(
        [1.2e7, 8e6, 1e7, 9e6, 1.1e7],
        closes=[1.10, 1.07, 1.04, 1.06, 1.095],
    )
    block = summarize_main_intent(cap, daily)
    assert block.ok
    assert "洗盘" in block.title


def test_intent_high_volume_flat_price_opposite_orders_reads_as_wash_trade():
    cap, daily = _days(
        [2e6, -1e6, 3e6, -2e6, 2.5e7],
        smalls=[1e6, 2e6, -1e6, 1e6, -1.8e7],
        closes=[1.05, 1.051, 1.049, 1.052, 1.053],
        vols=[1e8, 1.1e8, 9e7, 1.05e8, 2.8e8],
    )
    block = summarize_main_intent(cap, daily)
    assert block.ok
    assert "对倒" in block.title


def test_intent_intraday_spike_then_fade_reads_as_probe():
    cap, daily = _days([1e6], closes=[1.00], vols=[1e8])
    tick = pd.DataFrame({"price": [1.000, 1.018, 1.028, 1.012, 1.004]})
    block = summarize_main_intent(cap, daily, tick_df=tick)
    assert block.ok
    assert "试盘" in block.title
    assert any("分时" in e for e in block.evidence)


def test_intent_intraday_dump_then_reclaim_reads_as_wash():
    cap, daily = _days([1.2e7] * 5, closes=[1.10, 1.10, 1.10, 1.10, 1.10])
    tick = pd.DataFrame({"price": [1.100, 1.070, 1.045, 1.080, 1.098]})
    block = summarize_main_intent(cap, daily, tick_df=tick)
    assert block.ok
    assert "洗盘" in block.title


def test_intent_upper_wick_with_outflow_reads_as_distribute():
    cap, daily = _days(
        [-2e7] * 5,
        closes=[1.00, 1.01, 1.02, 1.03, 1.025],
        vols=[1e8, 1.1e8, 1.2e8, 1.3e8, 1.8e8],
    )
    daily["open"] = [1.00, 1.01, 1.02, 1.03, 1.028]
    daily["high"] = [1.01, 1.02, 1.03, 1.04, 1.055]
    daily["low"] = [0.995, 1.005, 1.015, 1.022, 1.022]
    block = summarize_main_intent(cap, daily)
    assert block.ok
    assert "出货" in block.title or "派发" in block.title
    assert any("上影" in e or "影线" in e for e in block.evidence)
