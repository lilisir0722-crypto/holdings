import json

import pandas as pd
import pytest

import holdings.journal as journal
from holdings.journal import (
    backfill_outcomes,
    load_checks,
    load_journal,
    mark_followed,
    note_bucket,
    record_check,
    record_snapshot,
    stance_bucket,
    summarize_outcomes,
    summarize_split,
)


def _kdf(start: str, days: int, step: float = 0.01) -> pd.DataFrame:
    dates = pd.bdate_range(start, periods=days)  # 工作日当交易日用
    return pd.DataFrame(
        {
            "date": [d.strftime("%Y-%m-%d") for d in dates],
            "close": [round(1.0 + i * step, 4) for i in range(days)],
        }
    )


@pytest.fixture(autouse=True)
def tmp_journal(tmp_path, monkeypatch):
    monkeypatch.setattr(journal, "DATA_DIR", tmp_path)
    return tmp_path


def test_record_and_load_roundtrip():
    ok = record_snapshot(
        "562590",
        name="半导体设备ETF华夏",
        price=1.041,
        cost=1.1424,
        stance="偏观望",
        trend="短线偏强",
        note="论证：……判断：观望。",
        note_status="ok",
        overseas_title="费半 -2.12%",
        defenses=[{"level": 1.027, "label": "8-14 底分型"}],
        confirm="收复 MA5",
        payload={"名称": "半导体设备ETF华夏", "现价": 1.041},
    )
    assert ok
    recs = load_journal("562590")
    assert len(recs) == 1
    r = recs[0]
    assert r["price"] == 1.041
    assert r["stance"] == "偏观望"
    assert r["defenses"][0]["level"] == 1.027
    assert r["payload"]["现价"] == 1.041
    assert r["ts"] and r["date"]


def test_dedup_same_day_price_stance():
    kw = dict(name="x", price=1.041, stance="偏观望")
    assert record_snapshot("562590", **kw)
    assert not record_snapshot("562590", **kw)  # 完全一样的连续刷新不记
    assert record_snapshot("562590", **{**kw, "price": 1.05})  # 价格变了要记
    assert len(load_journal("562590")) == 2


def test_load_newest_first_and_limit():
    for i in range(5):
        record_snapshot("562590", price=float(i), stance=f"s{i}")
    recs = load_journal("562590")
    assert recs[0]["price"] == 4.0  # 最新在前
    assert len(load_journal("562590", limit=3)) == 3


def test_load_missing_and_bad_lines(tmp_journal):
    assert load_journal("000000") == []
    p = tmp_journal / "562590.jsonl"
    p.write_text('{"price": 1.0}\n这不是json\n{"price": 2.0}\n', encoding="utf-8")
    recs = load_journal("562590")
    assert len(recs) == 2
    assert recs[0]["price"] == 2.0


def test_record_empty_code_noop():
    assert not record_snapshot("  ", price=1.0)


def test_backfill_fills_5d_and_10d():
    # 2026-08-03 是周一；快照在第 0 天，价 1.0
    record_snapshot("562590", price=1.0, stance="偏观望")
    # 把快照日期改到第 0 天（monkeypatch 不了 datetime，直接改文件）
    p = journal.DATA_DIR / "562590.jsonl"
    rec = json.loads(p.read_text(encoding="utf-8").strip())
    rec["date"] = "2026-08-03"
    p.write_text(json.dumps(rec, ensure_ascii=False) + "\n", encoding="utf-8")

    kdf = _kdf("2026-08-03", 15)  # close: 1.00, 1.01, ... 1.14
    n = backfill_outcomes("562590", kdf)
    assert n == 1
    rec = load_journal("562590")[0]
    assert rec["later"]["5d"]["close"] == 1.05
    assert rec["later"]["5d"]["chg_pct"] == 5.0
    assert rec["later"]["10d"]["close"] == 1.10
    # 再跑一次：已填的不重算
    assert backfill_outcomes("562590", kdf) == 0


def test_backfill_anchors_non_trading_day():
    record_snapshot("562590", price=1.0)
    p = journal.DATA_DIR / "562590.jsonl"
    rec = json.loads(p.read_text(encoding="utf-8").strip())
    rec["date"] = "2026-08-08"  # 周六
    p.write_text(json.dumps(rec, ensure_ascii=False) + "\n", encoding="utf-8")

    kdf = _kdf("2026-08-03", 15)
    backfill_outcomes("562590", kdf)
    later = load_journal("562590")[0]["later"]
    # 锚到 8-10 周一（索引 5），+5 个交易日 → 索引 10（8-17 周一）
    assert later["5d"]["date"] == "2026-08-17"


def test_backfill_waits_for_future_data():
    record_snapshot("562590", price=1.14)
    p = journal.DATA_DIR / "562590.jsonl"
    rec = json.loads(p.read_text(encoding="utf-8").strip())
    rec["date"] = "2026-08-17"  # 第 10 天（0 起）
    p.write_text(json.dumps(rec, ensure_ascii=False) + "\n", encoding="utf-8")

    kdf = _kdf("2026-08-03", 16)  # 索引 0-15：5d 够（15），10d 不够（20）
    backfill_outcomes("562590", kdf)
    later = load_journal("562590")[0]["later"]
    assert "5d" in later and "10d" not in later
    # 数据走到之后接着补
    kdf2 = _kdf("2026-08-03", 25)
    backfill_outcomes("562590", kdf2)
    later = load_journal("562590")[0]["later"]
    assert "10d" in later


def test_backfill_uses_anchor_close_when_price_missing():
    record_snapshot("562590", price=None)
    p = journal.DATA_DIR / "562590.jsonl"
    rec = json.loads(p.read_text(encoding="utf-8").strip())
    rec["date"] = "2026-08-03"
    p.write_text(json.dumps(rec, ensure_ascii=False) + "\n", encoding="utf-8")

    backfill_outcomes("562590", _kdf("2026-08-03", 15))
    later = load_journal("562590")[0]["later"]
    assert later["5d"]["chg_pct"] == 5.0  # 基准取锚定日收盘 1.0


def test_stance_bucket_order():
    assert stance_bucket("偏多信号更多，更宜谨慎加仓。") == "偏多"
    assert stance_bucket("短期偏空，别急着补。") == "偏空"
    assert stance_bucket("指标说法不一致，更宜观望。") == "观望"
    assert stance_bucket("偏观望") == "观望"
    assert stance_bucket("") == "其他"


def test_note_bucket_uses_judgement_section():
    note = "论证：KDJ 偏多、现价在 MA20 上方。判断：偏观望、略偏谨慎。"
    assert note_bucket(note) == "观望"  # 不能被论证里的「偏多」带偏
    assert note_bucket("判断：偏买。") == "偏多"
    assert note_bucket("判断：偏卖/观望。") == "偏空"


def test_summarize_split_rules_vs_notes():
    recs = [
        {
            "stance": "偏多信号更多",
            "note": "判断：偏观望。",
            "note_status": "ok",
            "later": {"5d": {"chg_pct": -3.0}},
        },
        {
            "stance": "更宜观望",
            "note": "判断：偏观望。",
            "note_status": "ok",
            "later": {"5d": {"chg_pct": 0.4}},
        },
        {
            "stance": "偏空",
            "note": "模型没写出来",
            "note_status": "error",
            "later": {"5d": {"chg_pct": -3.0}},
        },
    ]
    split = summarize_split(recs)
    rules = {r["bucket"]: r for r in split["规则"]}
    notes = {r["bucket"]: r for r in split["说明"]}
    assert rules["偏多"]["n5"] == 1 and rules["偏多"]["hit5"] == "0/1"
    assert rules["观望"]["hit5"] == "1/1"
    assert rules["偏空"]["hit5"] == "1/1"
    assert "偏多" not in notes  # 说明都判观望；失败的那条不计入
    assert notes["观望"]["n5"] == 2
    assert notes["观望"]["hit5"] == "1/2"


def test_record_and_mark_followed():
    cid = record_check(
        "562590",
        side="买",
        price=1.03,
        qty=5000,
        verdict="不符合",
        title="这笔买不符合预案。",
        reasons=["两头不靠"],
    )
    assert cid
    recs = load_checks("562590")
    assert recs[0]["followed"] is None
    assert mark_followed("562590", cid, False)
    recs = load_checks("562590")
    assert recs[0]["followed"] is False
    assert not mark_followed("562590", "no-such", True)


def test_summarize_outcomes_groups_and_hits():
    recs = [
        {"stance": "偏多信号更多", "later": {"5d": {"chg_pct": 3.0}, "10d": {"chg_pct": 4.0}}},
        {"stance": "偏多的延续", "later": {"5d": {"chg_pct": -2.0}}},
        {"stance": "偏空，别补", "later": {"5d": {"chg_pct": -3.0}}},
        {"stance": "更宜观望", "later": {"5d": {"chg_pct": 0.5}}},
        {"stance": "没有事后数据的", "later": {}},
    ]
    rows = {r["bucket"]: r for r in summarize_outcomes(recs)}
    assert rows["偏多"]["n5"] == 2
    assert rows["偏多"]["avg5"] == 0.5
    assert rows["偏多"]["hit5"] == "1/2"  # 一条 +3 说中，一条 -2 没说中
    assert rows["偏空"]["hit5"] == "1/1"
    assert rows["观望"]["hit5"] == "1/1"
    assert "其他" not in rows  # 没有事后数据的条目不参与
