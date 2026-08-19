from holdings.tech import analyze_indicators


def _macd_golden_cross_row():
    # last two: hist from neg to pos, dif crosses above dea
    return {
        "MACD_DIF": [0.01, 0.02],
        "MACD_DEA": [0.03, 0.015],
        "MACD_HIST": [-0.01, 0.005],
        "close": [1.0, 1.02],
    }


def test_macd_golden_cross_is_signal():
    report = analyze_indicators(_macd_golden_cross_row())
    names = [s.name for s in report.signals]
    assert "MACD" in names
    macd = next(s for s in report.signals if s.name == "MACD")
    assert "金叉" in macd.reading or "转强" in macd.reading
    assert macd.side == "多"


def test_conflicting_signals_say_watch():
    series = {
        "MACD_DIF": [0.01, 0.02],
        "MACD_DEA": [0.03, 0.015],
        "MACD_HIST": [-0.01, 0.005],
        "RSI": [80.0, 82.0],
        "close": [1.0, 1.02],
        "BOLL_UPPER": [1.0, 1.0],
        "BOLL_MID": [0.9, 0.9],
        "BOLL_LOWER": [0.8, 0.8],
    }
    report = analyze_indicators(series)
    assert "观望" in report.stance
    assert report.stance_evidence
    blob = "".join(report.stance_evidence)
    assert "MACD" in blob
    assert "RSI" in blob


def test_quiet_indicators_listed_separately():
    series = {
        "MACD_DIF": [0.02, 0.02],
        "MACD_DEA": [0.01, 0.01],
        "MACD_HIST": [0.01, 0.01],
        "ATR": [0.05, 0.05],
        "close": [1.0, 1.0],
    }
    report = analyze_indicators(series)
    quiet_names = [q.name for q in report.quiet]
    assert "ATR" in quiet_names


def test_overbought_rsi_is_bearish_signal():
    series = {
        "RSI": [55.0, 78.0],
        "close": [1.0, 1.05],
    }
    report = analyze_indicators(series)
    rsi = next(s for s in report.signals if s.name == "RSI")
    assert rsi.side == "空"
    assert "偏热" in rsi.reading or "超买" in rsi.reading


def test_kdj_has_plain_language_about():
    series = {
        "KDJ_K": [70.0, 81.5],
        "KDJ_D": [68.0, 74.4],
        "KDJ_J": [74.0, 95.8],
        "close": [1.0, 1.02],
    }
    report = analyze_indicators(series)
    kdj = next(s for s in report.signals if s.name == "KDJ")
    assert kdj.about
    assert "超买" in kdj.about or "80" in kdj.about
    assert "强弱" in kdj.about or "涨跌" in kdj.about or "动能" in kdj.about


def test_wr_has_plain_language_about():
    # easy_tdx WR 是 0~100 口径：小于 20 偏热（超买）
    series = {"WR1": [60.0, 15.0], "close": [1.0, 1.02]}
    report = analyze_indicators(series)
    wr = next(s for s in report.signals if s.name == "WR")
    assert wr.side == "空"
    assert wr.about
    assert "威廉" in wr.about or "高低" in wr.about
    assert "20" in wr.about or "超买" in wr.about


def test_wr_mid_value_is_not_a_signal():
    # 0~100 口径下 50 附近是中间值，不能报偏热
    series = {"WR1": [50.0, 51.5], "close": [1.0, 1.02]}
    report = analyze_indicators(series)
    assert "WR" not in [s.name for s in report.signals]
    wr = next(s for s in report.quiet if s.name == "WR")
    assert "中间" in wr.reading


def test_wr_oversold_is_bullish():
    series = {"WR1": [70.0, 85.0], "close": [1.0, 0.98]}
    report = analyze_indicators(series)
    wr = next(s for s in report.signals if s.name == "WR")
    assert wr.side == "多"
    assert "偏冷" in wr.reading


def test_bullish_with_no_cash_says_watch():
    from holdings.tech import enrich_with_account

    series = {
        "MACD_DIF": [0.01, 0.02],
        "MACD_DEA": [0.03, 0.015],
        "MACD_HIST": [-0.01, 0.005],
        "KDJ_K": [40.0, 45.0],
        "KDJ_D": [42.0, 40.0],
        "KDJ_J": [36.0, 55.0],
        "close": [1.0, 1.02],
        "MA5": [0.9, 1.01],
        "MA20": [0.85, 0.95],
    }
    report = analyze_indicators(series)
    # force bullish multi signal path if needed
    enriched = enrich_with_account(
        report,
        cash_total=0.0,
        cash_known=True,
        position_value=18000,
        book_value=26000,
    )
    assert "观望" in enriched.stance or "现金" in enriched.stance
    assert any("现金" in e for e in enriched.stance_evidence)


def test_bearish_mentions_loss_vs_cost_not_concentration():
    from holdings.tech import enrich_with_account

    series = {
        "KDJ_K": [70.0, 81.5],
        "KDJ_D": [68.0, 74.4],
        "KDJ_J": [74.0, 95.8],
        "WR1": [60.0, 15.0],
        "close": [1.0, 1.02],
    }
    report = analyze_indicators(series)
    enriched = enrich_with_account(
        report,
        cash_total=800,
        cash_known=True,
        position_value=18000,
        book_value=26000,
        cost=1.1424,
        price=1.05,
    )
    blob = enriched.stance + " ".join(enriched.stance_evidence)
    assert "现金" in blob
    assert "成本" in blob or "亏" in blob
    assert "降集中度" not in blob
    assert "偏重" not in enriched.stance


def test_trend_strong_when_above_ma20_and_up():
    from holdings.tech import judge_trend

    # 21 closes: up a lot, last above MA20
    closes = [1.0 + i * 0.01 for i in range(25)]
    series = {"close": closes, "MA5": closes, "MA20": [c - 0.05 for c in closes]}
    trend = judge_trend(series)
    assert "偏强" in trend.title
    assert trend.evidence


def test_trend_weak_when_below_ma20_and_down():
    from holdings.tech import judge_trend

    closes = [1.5 - i * 0.01 for i in range(25)]
    series = {"close": closes, "MA5": closes, "MA20": [c + 0.05 for c in closes]}
    trend = judge_trend(series)
    assert "偏弱" in trend.title


def test_trend_big_down_day_downgrades_from_strong():
    # 现价仍在 MA20 上方、MA5 在 MA20 上方，但单日大跌且跌破 MA5：不能再报偏强
    from holdings.tech import judge_trend

    closes = [1.06] * 20 + [1.127, 1.041]
    series = {"close": closes, "MA5": [1.0726] * 22, "MA20": [1.0198] * 22}
    trend = judge_trend(series)
    assert "偏强" not in trend.title
    assert any("最近一根 K 线" in e for e in trend.evidence)


def test_guides_cover_four_checks():
    from holdings.tech import analyze_indicators

    close = [1.0 + i * 0.002 for i in range(70)]
    close[40] = 0.85
    series = {
        "close": close,
        "MA5": close,
        "MA20": [c - 0.01 for c in close],
        "OBV": [100.0 + i for i in range(70)],
        "vol": [1e8] * 70,
        "DMI_ADX": [20.0] * 69 + [28.0],
    }
    report = analyze_indicators(series)
    titles = [g.title for g in report.guides]
    assert any("趋势还是震荡" in t for t in titles)
    assert any("量价" in t for t in titles)
    assert any("好不好拿" in t for t in titles)
    assert any("5 日" in t and "60 日" in t for t in titles)
    hold = next(g for g in report.guides if "好不好拿" in g.title)
    assert any("回撤" in e for e in hold.evidence)


def test_mfi_overbought_is_signal():
    series = {"MFI": [50.0, 85.0], "close": [1.0, 1.02]}
    report = analyze_indicators(series)
    mfi = next(s for s in report.signals if s.name == "MFI")
    assert mfi.side == "空"
    assert "偏热" in mfi.reading or "超买" in mfi.reading


def test_obv_diverges_from_price_is_signal():
    series = {
        "close": [1.0, 1.01, 1.02, 1.03, 1.05, 1.08],
        "OBV": [100.0, 99.0, 98.0, 97.0, 96.0, 90.0],
    }
    report = analyze_indicators(series)
    obv = next(s for s in report.signals if s.name == "OBV")
    assert "背离" in obv.reading or "量价" in obv.reading


def test_dmi_pdi_cross_up_is_bullish():
    series = {
        "DMI_PDI": [20.0, 28.0],
        "DMI_MDI": [25.0, 22.0],
        "DMI_ADX": [18.0, 26.0],
        "close": [1.0, 1.02],
    }
    report = analyze_indicators(series)
    dmi = next(s for s in report.signals if s.name == "DMI")
    assert dmi.side == "多"
    assert dmi.signal


def test_vr_extreme_is_signal():
    series = {"VR": [100.0, 460.0], "close": [1.0, 1.02]}
    report = analyze_indicators(series)
    vr = next(s for s in report.signals if s.name == "VR")
    assert vr.signal
    assert "偏热" in vr.reading or "偏高" in vr.reading


def test_llm_prompt_requires_argument():
    from holdings.llm import SYSTEM_PROMPT

    assert "论证" in SYSTEM_PROMPT
    assert "不要只丢一句" in SYSTEM_PROMPT


def test_deepseek_skipped_without_key(monkeypatch):
    from holdings import llm

    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    text, status = llm.explain_tech({"name": "测试"})
    assert status == "skipped"
    assert text is None




