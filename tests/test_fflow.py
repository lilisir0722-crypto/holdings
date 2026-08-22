import pandas as pd

from holdings import fflow


def test_upsert_stamps_blank_tdx_date(tmp_path, monkeypatch):
    monkeypatch.setattr(fflow, "DATA_DIR", tmp_path)
    df = pd.DataFrame(
        [{"date": "", "main_net": -4.17e7, "small_net": 4.17e7}]
    )
    out = fflow.upsert_snapshot("562590", df, today="2026-08-22")
    assert [r["date"] for r in out] == ["2026-08-21"]
    assert out[0]["main_net"] == -4.17e7
    assert out[0]["small_net"] == 4.17e7
    assert fflow.load("562590") == out


def test_upsert_overwrites_same_session(tmp_path, monkeypatch):
    monkeypatch.setattr(fflow, "DATA_DIR", tmp_path)
    fflow.save(
        "562590",
        [{"date": "2026-08-21", "main_net": 1.0, "small_net": 0.0}],
    )
    df = pd.DataFrame(
        [{"date": "", "main_net": -4.17e7, "small_net": 4.17e7}]
    )
    out = fflow.upsert_snapshot("562590", df, today="2026-08-22")
    assert len(out) == 1
    assert out[0]["main_net"] == -4.17e7


def test_upsert_appends_new_session(tmp_path, monkeypatch):
    monkeypatch.setattr(fflow, "DATA_DIR", tmp_path)
    fflow.save(
        "562590",
        [{"date": "2026-08-20", "main_net": 1.0, "small_net": 0.0}],
    )
    df = pd.DataFrame(
        [{"date": "", "main_net": -2.0, "small_net": 2.0}]
    )
    out = fflow.upsert_snapshot("562590", df, today="2026-08-21")
    assert [r["date"] for r in out] == ["2026-08-20", "2026-08-21"]
    assert out[0]["main_net"] == 1.0
    assert out[1]["main_net"] == -2.0


def test_upsert_keeps_store_when_snapshot_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(fflow, "DATA_DIR", tmp_path)
    fflow.save(
        "562590",
        [{"date": "2026-08-20", "main_net": 1.0, "small_net": 0.0}],
    )
    out = fflow.upsert_snapshot("562590", pd.DataFrame(), today="2026-08-22")
    assert [r["date"] for r in out] == ["2026-08-20"]
    assert out[0]["main_net"] == 1.0
