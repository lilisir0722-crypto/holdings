import time
from unittest.mock import MagicMock

import pandas as pd

from holdings.market import fetch_market_context
from holdings.tech import summarize_capital


def test_summarize_capital_latest_main_net():
    df = pd.DataFrame(
        [
            {"date": "2026-08-14", "main_net": -1e7, "small_net": 2e6},
            {"date": "2026-08-15", "main_net": 3e7, "small_net": -5e6},
        ]
    )
    block = summarize_capital(df)
    assert block.ok
    assert "主力" in block.title or "净流入" in block.title
    assert any("3" in e or "3000" in e or "流入" in e for e in block.evidence)
    assert "立即买入" not in block.title


def test_summarize_capital_empty():
    block = summarize_capital(pd.DataFrame())
    assert not block.ok
    assert "没有资金流向" in block.title or "暂无" in block.title


def test_summarize_capital_none():
    block = summarize_capital(None)
    assert not block.ok
    assert "没有资金流向" in block.title or "暂无" in block.title


def test_summarize_capital_missing_date_column():
    df = pd.DataFrame([{"main_net": 1e7, "small_net": 0}])
    block = summarize_capital(df)
    assert not block.ok
    assert "没有资金流向" in block.title or "暂无" in block.title


def test_summarize_capital_nan_main_net():
    df = pd.DataFrame(
        [{"date": "2026-08-15", "main_net": float("nan"), "small_net": 0}]
    )
    block = summarize_capital(df)
    assert not block.ok
    blob = block.title + "".join(block.evidence)
    assert "nan" not in blob.lower()


def test_summarize_capital_negative_main_net():
    df = pd.DataFrame(
        [{"date": "2026-08-15", "main_net": -3e7, "small_net": 0}]
    )
    block = summarize_capital(df)
    assert block.ok
    assert block.summary_line is not None
    assert "负" in block.summary_line


def test_summarize_capital_blank_date_still_uses_main_net():
    df = pd.DataFrame(
        [{"date": "", "main_net": -4.17e7, "small_net": 4.17e7}]
    )
    block = summarize_capital(df)
    assert block.ok
    assert "主力" in block.title
    assert any("4171" in e or "万" in e for e in block.evidence)
    assert "没有资金流向" not in block.title


def test_fetch_market_context_pulls_tdx_capital():
    client = MagicMock()
    cap_df = pd.DataFrame([{"date": "", "main_net": -4.17e7, "small_net": 4.17e7}])
    belong_df = pd.DataFrame([{"name": "行业", "code": "HY001"}])
    client.get_capital_flow.return_value = cap_df
    client.get_belong_board.return_value = belong_df
    client.get_unusual.return_value = pd.DataFrame()
    client.get_board_summary.return_value = {}

    out = fetch_market_context(client, "600000")

    assert out["error"] is None
    assert out["capital_df"] is cap_df
    assert out["belong_df"] is belong_df
    client.get_capital_flow.assert_called_once()
    client.get_belong_board.assert_called_once()


def test_fetch_market_context_belong_fails_only():
    client = MagicMock()
    cap_df = pd.DataFrame([{"date": "", "main_net": -4.17e7}])
    client.get_capital_flow.return_value = cap_df
    client.get_belong_board.side_effect = RuntimeError("belong fail")
    client.get_unusual.return_value = pd.DataFrame()

    out = fetch_market_context(client, "600000")

    assert out["error"] == "belong: belong fail"
    assert out["capital_df"] is cap_df
    assert out["belong_df"] is None
    client.get_capital_flow.assert_called_once()


def test_pick_boards_prefers_few():
    from holdings.tech import pick_boards

    belong = pd.DataFrame(
        [
            {"board_code": "880001", "board_name": "半导体", "board_type": 2},
            {"board_code": "880002", "board_name": "机器人概念", "board_type": 3},
            {"board_code": "880003", "board_name": "杂鱼", "board_type": 9},
        ]
    )
    summaries = {
        "880001": {
            "member_count": 40,
            "amount": 1e10,
            "main_net_amount": -2e8,
            "main_net_3d": -1e8,
            "main_net_5d": 5e7,
            "up_count": 10,
            "down_count": 20,
        }
    }
    blocks = pick_boards(belong, summaries, limit=2)
    assert 1 <= len(blocks) <= 2
    assert blocks[0].ok
    assert "半导体" in blocks[0].title
    assert any("主力" in e for e in blocks[0].evidence)


def test_attach_market_context_none_still_shows_fallback():
    from holdings.tech import TechReport, attach_market_context

    report = TechReport(stance="更宜观望。", stance_evidence=[], signals=[], quiet=[])
    out = attach_market_context(report, None)
    assert out.capital is not None
    assert not out.capital.ok
    assert "资金流向" in out.capital.title or "暂无" in out.capital.title
    assert out.boards
    assert not out.boards[0].ok
    assert out.unusual is not None
    assert not out.unusual.ok


def test_summarize_unusual_keeps_this_code_only():
    from holdings.tech import summarize_unusual

    df = pd.DataFrame(
        [
            {"code": "562590", "name": "半导体", "time": "10:00", "desc": "大笔买入", "value": "1"},
            {"code": "000001", "name": "平安", "time": "10:01", "desc": "涨停", "value": "2"},
        ]
    )
    block = summarize_unusual(df, "562590")
    assert block.ok
    blob = "".join(block.evidence)
    assert "大笔买入" in blob
    assert "平安" not in blob
    assert "立即买入" not in block.title


def test_summarize_unusual_empty():
    from holdings.tech import summarize_unusual

    block = summarize_unusual(pd.DataFrame(), "562590")
    assert not block.ok
    assert "没出现" in block.title or "暂无" in block.title


def test_chanlun_from_dict_lists_all_sections():
    from holdings.tech import chanlun_from_dict

    block = chanlun_from_dict(
        {
            "kline_count": 80,
            "ckline_count": 60,
            "fractal_count": 1,
            "bi_count": 1,
            "zs_count": 1,
            "xd_count": 1,
            "mmd_count": 1,
            "bc_count": 1,
            "fractals": [{"index": 0, "type": "ding", "val": 1.2, "date": "2026-08-15", "done": True}],
            "bis": [
                {
                    "index": 0,
                    "direction": "up",
                    "start_date": "2026-08-01",
                    "end_date": "2026-08-10",
                    "high": 1.2,
                    "low": 1.0,
                    "done": True,
                }
            ],
            "zss": [
                {
                    "index": 0,
                    "zg": 1.1,
                    "zd": 1.05,
                    "gg": 1.2,
                    "dd": 1.0,
                    "line_count": 3,
                    "start_date": "2026-08-01",
                    "end_date": "2026-08-10",
                    "done": True,
                }
            ],
            "xds": [
                {
                    "index": 0,
                    "direction": "down",
                    "start_date": "2026-08-01",
                    "end_date": "2026-08-15",
                    "high": 1.2,
                    "low": 1.0,
                }
            ],
            "mmds": [{"type": "1buy", "date": "2026-08-10", "msg": "一类买点"}],
            "bcs": [{"type": "bi", "curr_date": "2026-08-10", "msg": "笔背驰"}],
        }
    )
    assert block.ok
    assert block.counts["买卖点"] == 1
    assert block.mmds[0]["type"] == "1buy"
    assert block.fractals[0]["type"] == "ding"
    assert "论证" in block.note


def test_klines_from_dataframe():
    from holdings.tech import klines_from_dataframe

    df = pd.DataFrame(
        [
            {"datetime": "2026-08-01 00:00:00", "open": 1.0, "high": 1.1, "low": 0.9, "close": 1.05},
            {"datetime": "2026-08-02", "open": 1.05, "high": 1.2, "low": 1.0, "close": 1.1},
        ]
    )
    rows = klines_from_dataframe(df)
    assert len(rows) == 2
    assert rows[0]["date"] == "2026-08-01"
    assert rows[1]["close"] == 1.1


def test_chanlun_from_dict_keeps_klines():
    from holdings.tech import chanlun_from_dict

    block = chanlun_from_dict(
        {
            "kline_count": 1,
            "klines": [{"date": "2026-08-01", "open": 1, "high": 1.1, "low": 0.9, "close": 1}],
            "bis": [],
            "zss": [],
            "mmds": [],
            "bcs": [],
            "fractals": [],
            "xds": [],
        }
    )
    assert block.ok
    assert block.klines[0]["date"] == "2026-08-01"


def test_pick_boards_empty_belong():
    from holdings.tech import pick_boards

    blocks = pick_boards(pd.DataFrame(), {}, limit=2)
    assert len(blocks) == 1
    assert not blocks[0].ok
    blob = blocks[0].title + "".join(blocks[0].evidence)
    assert "暂无" in blob or "对不上" in blob


def test_board_ranks_cached_for_second_fetch():
    from holdings import market

    market.clear_board_rank_cache()
    client = MagicMock()
    rank_df = pd.DataFrame([{"code": "880001", "name": "半导体", "change_pct": 1.2}])
    client.get_belong_board.return_value = pd.DataFrame([{"name": "行业", "code": "HY001"}])
    client.get_unusual.return_value = pd.DataFrame()
    client.get_board_summary.return_value = {}
    client.get_board_change_ranking.return_value = rank_df

    fetch_market_context(client, "600000")
    first = client.get_board_change_ranking.call_count
    assert first == 4
    fetch_market_context(client, "510300")
    assert client.get_board_change_ranking.call_count == first


def test_board_ranks_run_in_parallel(monkeypatch):
    from holdings import market

    market.clear_board_rank_cache()

    def fake_connect(host, timeout=10.0):
        c = MagicMock()

        def ranking(btype, days=20):
            time.sleep(0.25)
            return pd.DataFrame([{"code": "880001", "change_pct": 1.0}])

        c.get_board_change_ranking.side_effect = ranking
        return c

    monkeypatch.setattr(market, "_connect_mac", fake_connect)
    client = MagicMock()
    client._host = "1.2.3.4"
    t0 = time.monotonic()
    r1, r20 = market.fetch_board_ranks(client)
    elapsed = time.monotonic() - t0
    assert r1 and r20
    assert elapsed < 0.7
