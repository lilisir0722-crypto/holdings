import json

import pytest

import holdings.journal as journal
from holdings.journal import load_journal, record_snapshot


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
