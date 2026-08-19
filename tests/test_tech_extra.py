from datetime import date

import pandas as pd

from holdings.tech import TechReport, TrendJudgment, judge_trend
from holdings.tech_extra import (
    apply_timeframe_stance,
    attach_board_ranks,
    is_listed_etf,
    parse_eastmoney_etf_quote,
    summarize_etf,
    summarize_intraday,
    summarize_relative,
    summarize_timeframes,
    summarize_xdxr,
    trend_side,
)


def _closes(kind: str) -> list[float]:
    if kind == "strong":
        return [1.0 + i * 0.005 for i in range(30)]
    if kind == "weak":
        return [1.15 - i * 0.005 for i in range(30)]
    return [1.0 + (0.001 if i % 2 == 0 else -0.001) for i in range(30)]


def _trend(kind: str) -> TrendJudgment:
    return judge_trend({"close": _closes(kind)})


def test_judge_trend_fixtures_have_expected_sides():
    assert trend_side(_trend("strong").title) == "多"
    assert trend_side(_trend("weak").title) == "空"
    assert trend_side(_trend("chop").title) == "中"


def test_timeframe_conflict_overrides_stance_to_watch():
    report = TechReport(
        stance="偏多信号更多，更宜谨慎加仓。",
        stance_evidence=["MACD 金叉"],
        signals=[],
        quiet=[],
        trend_title=_trend("strong").title,
        trend_evidence=list(_trend("strong").evidence),
    )
    weekly = _trend("weak")
    min60 = _trend("chop")
    out = apply_timeframe_stance(report, daily=_trend("strong"), weekly=weekly, min60=min60)
    assert "观望" in out.stance
    blob = "".join(out.stance_evidence)
    assert "日线" in blob and "周线" in blob
    assert "偏强" in blob and "偏弱" in blob


def test_aligned_timeframes_keep_stance():
    report = TechReport(
        stance="偏多信号更多，更宜谨慎加仓。",
        stance_evidence=["MACD 金叉"],
        signals=[],
        quiet=[],
        trend_title=_trend("strong").title,
    )
    out = apply_timeframe_stance(
        report,
        daily=_trend("strong"),
        weekly=_trend("strong"),
        min60=_trend("chop"),
    )
    assert "加仓" in out.stance
    assert "观望" not in out.stance or "更宜谨慎加仓" in out.stance


def test_summarize_timeframes_lists_three_sides():
    block = summarize_timeframes(_trend("strong"), _trend("weak"), _trend("chop"))
    assert block.ok
    assert "偏强" in block.title
    assert "偏弱" in block.title
    assert "震荡" in block.title


def test_summarize_relative_says_who_is_stronger():
    self_c = [1.0] * 61 + [1.10]
    hs = [1.0] * 61 + [1.02]
    board = [1.0] * 61 + [1.20]
    block = summarize_relative(self_c, hs, "半导体", board)
    assert block.ok
    blob = "".join(block.evidence)
    assert "沪深300" in blob
    assert "半导体" in blob
    assert "60" in blob


def test_attach_board_ranks_writes_place():
    from holdings.tech import BoardBlock

    boards = [BoardBlock(title="半导体（880001）", evidence=["主力净流入 1 亿"], ok=True)]
    rank = pd.DataFrame(
        [
            {"code": "880099", "name": "其它", "change_pct": 3.0},
            {"code": "880001", "name": "半导体", "change_pct": 1.2},
        ]
    )
    out = attach_board_ranks(boards, rank_1d=rank, rank_20d=rank)
    blob = "".join(out[0].evidence)
    assert "第 2" in blob or "第2" in blob
    assert "1.2" in blob or "1.20" in blob


def test_summarize_intraday_open_vs_prev():
    tick = pd.DataFrame(
        [
            {"time": "09:30", "price": 1.00, "vol": 100},
            {"time": "10:00", "price": 1.05, "vol": 80},
            {"time": "14:50", "price": 1.02, "vol": 60},
        ]
    )
    auction = pd.DataFrame([{"time": "09:25", "price": 1.01, "matched": 5000, "unmatched": 100}])
    block = summarize_intraday(tick, auction, prev_close=1.00)
    assert block.ok
    blob = block.title + "".join(block.evidence)
    assert "竞价" in blob
    assert "回落" in blob or "冲高" in blob


def test_summarize_intraday_empty():
    block = summarize_intraday(None, None, prev_close=1.0)
    assert not block.ok
    assert "没有分时" in block.title


def test_summarize_intraday_close_near_low():
    tick = pd.DataFrame(
        [
            {"time": "09:30", "price": 1.089, "vol": 100},
            {"time": "10:30", "price": 1.102, "vol": 80},
            {"time": "15:00", "price": 1.041, "vol": 60},
        ]
    )
    block = summarize_intraday(tick, None, prev_close=1.127)
    blob = "".join(block.evidence)
    assert "低位" in blob


def test_summarize_xdxr_lists_recent_split():
    df = pd.DataFrame(
        [
            {
                "year": 2026,
                "month": 7,
                "day": 10,
                "category": 11,
                "name": "扩缩股",
                "suogu": 0.5,
                "fenhong": None,
                "songzhuangu": None,
            }
        ]
    )
    block = summarize_xdxr(df, as_of=date(2026, 8, 18))
    assert block.ok
    blob = block.title + "".join(block.evidence)
    assert "拆分" in blob or "扩缩" in blob
    assert "复权" in blob


def test_summarize_xdxr_empty():
    block = summarize_xdxr(pd.DataFrame(), as_of=date(2026, 8, 18))
    assert not block.ok
    assert "没有除权" in block.title or "没有" in block.title


def test_is_listed_etf():
    assert is_listed_etf("562590")
    assert is_listed_etf("159530")
    assert is_listed_etf("510300")
    assert not is_listed_etf("000001")
    assert not is_listed_etf("110011")


def test_parse_and_summarize_etf_premium():
    raw = {"data": {"f43": 1.05, "f46": 1.00, "f116": 8e9, "f58": "某ETF"}}
    parsed = parse_eastmoney_etf_quote(raw)
    block = summarize_etf(parsed, track_60=None, self_60=0.08)
    assert block.ok
    blob = block.title + "".join(block.evidence)
    assert "溢价" in blob
    assert "5.0%" in blob or "5%" in blob
    assert "跟踪误差暂无" in blob


def test_summarize_etf_missing():
    block = summarize_etf({}, track_60=None, self_60=None)
    assert not block.ok
    assert "暂无" in block.title


def test_summarize_etf_large_discount_warns_iopv():
    parsed = {"price": 1.041, "iopv": 1.087, "size": 8e9}
    block = summarize_etf(parsed, track_60=None, self_60=None)
    blob = "".join(block.evidence)
    assert "折价" in blob
    assert "核对 IOPV" in blob


def test_summarize_etf_gmbd_shares():
    parsed = {"price": 1.041, "iopv": 1.087, "size": 8.881e9}
    gmbd = [
        {"date": "2026-07-03", "subs": "---", "redm": "---", "shares": "69.47", "nav": "---", "change": "---"},
        {"date": "2026-06-30", "subs": "25.94", "redm": "20.25", "shares": "20.10", "nav": "83.19", "change": "235.83%"},
    ]
    block = summarize_etf(parsed, gmbd=gmbd)
    blob = "".join(block.evidence)
    assert "69.47" in blob and "20.10" in blob
    assert "申购 25.94" in blob and "赎回 20.25" in blob
    assert "涌入" in blob


def test_summarize_etf_without_gmbd_unchanged():
    parsed = {"price": 1.041, "iopv": 1.087, "size": 8.881e9}
    block = summarize_etf(parsed)
    assert all("份额" not in e for e in block.evidence)
