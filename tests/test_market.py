from holdings.market import kline_window_after_jumps, rank_mac_hosts


def test_shanghai_codes():
    from holdings.market import infer_market

    assert infer_market("600519") == "SH"
    assert infer_market("510300") == "SH"
    assert infer_market("688981") == "SH"


def test_rank_mac_hosts_puts_fastest_first():
    ranked = [("b", 0.2), ("a", 0.1), ("c", 0.5)]
    order = rank_mac_hosts(["a", "b", "c", "d"], ranked)
    assert order[0] == "a"
    assert order[1] == "b"
    assert "d" in order



def test_shenzhen_codes():
    from holdings.market import infer_market

    assert infer_market("000001") == "SZ"
    assert infer_market("300750") == "SZ"
    assert infer_market("159915") == "SZ"


def test_kline_window_starts_after_share_split():
    import pandas as pd

    dates = pd.date_range("2026-06-01", periods=10, freq="D")
    close = [3.6, 3.7, 3.8, 3.69, 1.23, 1.20, 1.18, 1.10, 1.05, 1.05]
    high = [c + 0.05 for c in close]
    low = [c - 0.05 for c in close]
    df = pd.DataFrame({"datetime": dates, "close": close, "high": high, "low": low})
    window = kline_window_after_jumps(df)
    assert float(window["close"].iloc[0]) == 1.23
    assert float(window["high"].max()) < 2


def test_split_adjusted_peak_uses_pre_split_high():
    import pandas as pd
    from holdings.market import split_adjusted_peak

    dates = pd.date_range("2026-06-01", periods=8, freq="D")
    close = [3.60, 3.80, 4.25, 3.69, 1.23, 1.20, 1.10, 1.05]
    df = pd.DataFrame({"datetime": dates, "close": close, "high": close, "low": close})
    peak_price, peak_date, last, drawdown = split_adjusted_peak(df)
    assert peak_date == "2026-06-03"
    assert abs(peak_price - 4.25 * (1.23 / 3.69)) < 0.02
    assert last == 1.05
    assert drawdown < -0.2


def test_daily_returns_do_not_include_share_split_crash():
    import pandas as pd
    from holdings.market import daily_returns_from_kline

    dates = pd.date_range("2026-06-01", periods=8, freq="D")
    close = [3.60, 3.80, 4.25, 3.69, 1.23, 1.20, 1.10, 1.05]
    df = pd.DataFrame({"datetime": dates, "close": close})
    rets = daily_returns_from_kline(df)
    assert rets
    assert max(abs(r) for r in rets) < 0.4


def test_listed_etf_stays_on_exchange():
    from holdings.market import is_otc_fund

    assert is_otc_fund("基金", "110022")
    assert is_otc_fund("基金", "000198")
    assert not is_otc_fund("基金", "562590")
    assert not is_otc_fund("基金", "159530")
    assert not is_otc_fund("股票", "000001")


def test_parse_eastmoney_otc_quote():
    from holdings.market import parse_eastmoney_otc_quote

    raw = {
        "data": {
            "f43": 2.928,
            "f57": "110022",
            "f58": "易方达消费行业股票",
            "f60": 2.949,
            "f170": -0.71,
        }
    }
    q = parse_eastmoney_otc_quote(raw)
    assert q["name"] == "易方达消费行业股票"
    assert q["price"] == 2.928
    assert abs(q["day_change_pct"] - (-0.0071)) < 1e-6


def test_parse_fund_holdings_table():
    from holdings.market import parse_fund_holdings

    html = """
    截止至：<font class='px12'>2026-06-30</font>
    <td class='tol'><a href='//quote.eastmoney.com/unify/r/1.688012'>中微公司</a></td>
    <td class='tol'><a href='//quote.eastmoney.com/unify/r/1.002371'>北方华创</a></td>
    """
    names, asof = parse_fund_holdings(html)
    assert asof == "2026-06-30"
    assert names[:2] == ["中微公司", "北方华创"]


def test_parse_fund_gmbd():
    from holdings.market import parse_fund_gmbd

    html = """
    <table><thead><tr><th>日期</th></tr></thead><tbody>
    <tr><td>2026-07-03</td><td class='tor'>---</td><td class='tor'>---</td><td class='tor'>69.47</td><td class='tor'>---</td><td class='tor'>---</td></tr>
    <tr><td>2026-06-30</td><td class='tor'>25.94</td><td class='tor'>20.25</td><td class='tor'>20.10</td><td class='tor'>83.19</td><td class='tor'>235.83%</td></tr>
    </tbody></table>
    """
    rows = parse_fund_gmbd(html)
    assert len(rows) == 2
    assert rows[0]["date"] == "2026-07-03"
    assert rows[0]["shares"] == "69.47"
    assert rows[1]["subs"] == "25.94"
    assert rows[1]["redm"] == "20.25"
    assert parse_fund_gmbd("") == []
    assert parse_fund_gmbd("no table here") == []
