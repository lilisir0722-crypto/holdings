import pytest

import holdings.overseas as overseas
from holdings.overseas import (
    attach_overseas,
    fetch_overseas_cached,
    parse_futures_payload,
    parse_overseas_payload,
    pick_pack,
    summarize_overseas,
    watchlist_for,
)
from holdings.tech import TechReport


def _payload():
    return {
        "data": {
            "diff": [
                {"f12": "SOX", "f13": 251, "f14": "费城半导体指数", "f2": 11831.1, "f3": -1.35, "f124": 1787152800},
                {"f12": "AMAT", "f13": 105, "f14": "应用材料", "f2": 495.675, "f3": -3.63, "f124": 1787152800},
                {"f12": "MU", "f13": 105, "f14": "美光科技", "f2": 939.35, "f3": -0.15, "f124": 1787152800},
                {"f12": "002371", "f13": 0, "f14": "北方华创", "f2": 712.95, "f3": -8.24, "f124": 1787152800},
                {"f12": "931743", "f13": 2, "f14": "半导体材料设备", "f2": 5123.4, "f3": -7.10, "f124": 1787152800},
                {"f12": "US30Y", "f13": 171, "f14": "美国30年期国债收益率", "f2": 5.2088, "f3": -1.48, "f124": 1787152800},
                {"f12": "US10Y", "f13": 171, "f14": "美国10年期国债收益率", "f2": 4.6506, "f3": 0.04, "f124": 1787152800},
                {"f12": "UDI", "f13": 100, "f14": "美元指数", "f2": 98.83, "f3": 0.03, "f124": 1787152800},
                {"f12": "USDCNH", "f13": 133, "f14": "美元兑离岸人民币", "f2": 6.7321, "f3": 0.01, "f124": 1787152800},
                {"f12": "BROKEN", "f13": 105, "f14": "无价", "f2": "-", "f3": "-"},
            ]
        }
    }


def _futures_payload(price=29653.35, zdf=0.48):
    return {
        "qt": {
            "dm": "NQ00Y",
            "name": "小型纳指当月连续",
            "p": price,
            "zdf": zdf,
            "spsj": 1787259600,
        }
    }


def test_parse_overseas_payload_extracts_and_skips_bad_rows():
    quotes = parse_overseas_payload(_payload())
    assert set(quotes) == {
        "251.SOX", "105.AMAT", "105.MU", "0.002371", "2.931743",
        "171.US30Y", "171.US10Y", "100.UDI", "133.USDCNH",
    }
    sox = quotes["251.SOX"]
    assert sox["name"] == "费城半导体指数"
    assert sox["price"] == 11831.1
    assert sox["change_pct"] == -1.35
    assert sox["ts"] == 1787152800


def test_parse_overseas_payload_empty():
    assert parse_overseas_payload(None) == {}
    assert parse_overseas_payload({}) == {}


def test_parse_futures_payload():
    q = parse_futures_payload(_futures_payload(), "纳指期货")
    assert q["name"] == "小型纳指当月连续"
    assert q["price"] == 29653.35
    assert q["change_pct"] == 0.48
    assert q["ts"] == 1787259600
    assert parse_futures_payload(None, "x") is None
    assert parse_futures_payload({"qt": {"p": "-"}}, "x") is None


def test_summarize_overseas_groups_and_hint():
    block = summarize_overseas(parse_overseas_payload(_payload()), pack="半导体")
    assert block.ok
    assert "费半" in block.title
    blob = "".join(block.evidence)
    assert "应用材料" in blob and "美光" in blob
    assert "美国30年期国债收益率" in blob and "回落" in blob
    assert "幅度一般" in blob  # -1.35% 落在 1~3 之间


def test_summarize_overseas_new_groups():
    block = summarize_overseas(parse_overseas_payload(_payload()), pack="半导体")
    blob = "".join(block.evidence)
    assert "龙头：北方华创 -8.24%" in blob
    assert "行业：半导体材料设备 -7.10%" in blob
    assert "美国10年期国债收益率 4.6506%，持平" in blob  # 0.04% 小于 0.05 的持平阈值
    assert "美元指数 98.8300" in blob
    assert "USDCNH 上行" in blob  # 汇率注释


def test_summarize_overseas_futures_group_and_hint():
    quotes = parse_overseas_payload(_payload())
    quotes["103.NQ00Y"] = parse_futures_payload(_futures_payload(zdf=1.24), "纳指期货")
    block = summarize_overseas(quotes, pack="半导体")
    blob = "".join(block.evidence)
    assert "期货：小型纳指当月连续 +1.24%" in blob
    assert "高开" in blob
    assert "纳指期货 +1.24%" in block.title


def test_summarize_overseas_futures_quiet_no_hint():
    quotes = parse_overseas_payload(_payload())
    quotes["103.NQ00Y"] = parse_futures_payload(_futures_payload(zdf=0.48), "纳指期货")
    block = summarize_overseas(quotes, pack="半导体")
    blob = "".join(block.evidence)
    assert "期货：" in blob
    assert "高开" not in blob and "低开" not in blob


def test_pick_pack_by_name_and_boards():
    assert pick_pack("半导体设备ETF华夏") == "半导体"
    assert pick_pack("机器人ETF易方达") == "机器人"
    assert pick_pack("芯片ETF") == "半导体"
    assert pick_pack("东方电气") == "电力设备"
    assert pick_pack("贵州茅台") is None
    assert pick_pack("某某股票", ["电源设备", "机器人概念"]) == "机器人"
    assert pick_pack("", []) is None


def test_macro_only_when_no_pack():
    block = summarize_overseas(parse_overseas_payload(_payload()), pack=None)
    blob = "".join(block.evidence)
    assert "利率：" in blob and "汇率：" in blob
    assert "设备：" not in blob and "龙头：" not in blob and "行业：" not in blob
    assert "费半" not in block.title


def test_robot_pack_groups():
    raw = _payload()
    raw["data"]["diff"] += [
        {"f12": "TSLA", "f13": 105, "f14": "特斯拉", "f2": 300.5, "f3": 1.2, "f124": 1787152800},
        {"f12": "300124", "f13": 0, "f14": "汇川技术", "f2": 60.1, "f3": -4.2, "f124": 1787152800},
        {"f12": "980022", "f13": 0, "f14": "机器人产业", "f2": 2100.0, "f3": -3.3, "f124": 1787152800},
    ]
    block = summarize_overseas(parse_overseas_payload(raw), pack="机器人")
    blob = "".join(block.evidence)
    assert "海外：特斯拉 +1.20%" in blob
    assert "龙头：汇川技术 -4.20%" in blob
    assert "行业：机器人产业 -3.30%" in blob
    assert "设备：" not in blob  # 半导体包的内容不出现


def test_watchlist_for_includes_common():
    semi = dict(watchlist_for("半导体"))
    assert "171.US30Y" in semi and "251.SOX" in semi
    macro = dict(watchlist_for(None))
    assert "171.US30Y" in macro and "251.SOX" not in macro


def test_power_pack_match_and_groups():
    assert pick_pack("东方电气") == "电力设备"
    assert pick_pack("某某", ["电力设备"]) == "电力设备"
    raw = _payload()
    raw["data"]["diff"] += [
        {"f12": "GEV", "f13": 106, "f14": "GE Vernova Inc", "f2": 987.46, "f3": -1.7, "f124": 1787152800},
        {"f12": "600875", "f13": 1, "f14": "东方电气", "f2": 25.91, "f3": -6.06, "f124": 1787152800},
        {"f12": "980148", "f13": 0, "f14": "电力设备", "f2": 2933.21, "f3": -5.65, "f124": 1787152800},
    ]
    block = summarize_overseas(parse_overseas_payload(raw), pack="电力设备")
    blob = "".join(block.evidence)
    assert "海外：GE Vernova Inc -1.70%" in blob
    assert "龙头：东方电气 -6.06%" in blob
    assert "行业：电力设备 -5.65%" in blob
    assert "设备：" not in blob


def test_summarize_overseas_big_drop_warns():
    quotes = parse_overseas_payload(_payload())
    quotes["251.SOX"]["change_pct"] = -4.98
    block = summarize_overseas(quotes, pack="半导体")
    assert "承压" in "".join(block.evidence)


def test_summarize_overseas_empty():
    block = summarize_overseas({})
    assert not block.ok
    assert "暂时没有" in block.title


def test_attach_overseas_never_breaks(monkeypatch):
    monkeypatch.setattr(
        "holdings.overseas.fetch_overseas_cached",
        lambda pack=None, timeout=8.0: (None, 0.0, False),
    )
    report = TechReport(stance="x", stance_evidence=[], signals=[], quiet=[])
    out = attach_overseas(report, name="半导体设备ETF华夏")
    assert out.overseas is not None
    assert not out.overseas.ok


def test_attach_overseas_stale_cache_note(monkeypatch):
    import time as _time

    quotes = parse_overseas_payload(_payload())
    monkeypatch.setattr(
        "holdings.overseas.fetch_overseas_cached",
        lambda pack=None, timeout=8.0: (quotes, _time.time() - 3600, False),
    )
    report = TechReport(stance="x", stance_evidence=[], signals=[], quiet=[])
    out = attach_overseas(report, name="半导体设备ETF华夏")
    assert out.overseas.ok
    assert "缓存" in out.overseas.evidence[-1]


def test_attach_overseas_fresh_or_ttl_cache_no_note(monkeypatch):
    import time as _time

    quotes = parse_overseas_payload(_payload())
    monkeypatch.setattr(
        "holdings.overseas.fetch_overseas_cached",
        lambda pack=None, timeout=8.0: (quotes, _time.time() - 30, False),
    )
    report = TechReport(stance="x", stance_evidence=[], signals=[], quiet=[])
    out = attach_overseas(report, name="半导体设备ETF华夏")
    assert out.overseas.ok
    assert not any("缓存" in e for e in out.overseas.evidence)


@pytest.fixture
def tmp_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(overseas, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(overseas.time, "sleep", lambda s: None)  # 重试不等
    return tmp_path


def test_cached_fresh_fetch_writes_cache(tmp_cache, monkeypatch):
    calls = {"n": 0}

    def fake(timeout=8.0, pack=None):
        calls["n"] += 1
        return {"251.SOX": {"name": "费城半导体指数", "price": 100.0, "change_pct": 1.0, "ts": None}}

    monkeypatch.setattr(overseas, "fetch_overseas", fake)
    quotes, _at, fresh = fetch_overseas_cached(pack="半导体")
    assert fresh and quotes["251.SOX"]["price"] == 100.0
    # TTL 内第二次：不打请求
    quotes2, _at2, fresh2 = fetch_overseas_cached(pack="半导体")
    assert not fresh2 and calls["n"] == 1 and quotes2 == quotes
    # 另一个包是另一份缓存
    fetch_overseas_cached(pack=None)
    assert calls["n"] == 2


def test_cached_empty_triggers_retry(tmp_cache, monkeypatch):
    calls = {"n": 0}
    waits: list[float] = []
    monkeypatch.setattr(overseas.time, "sleep", lambda s: waits.append(s))

    def flaky(timeout=8.0, pack=None):
        calls["n"] += 1
        return {} if calls["n"] < 3 else {"100.NDX": {"name": "纳斯达克", "price": 1.0, "change_pct": 0.1, "ts": None}}

    monkeypatch.setattr(overseas, "fetch_overseas", flaky)
    quotes, _at, fresh = fetch_overseas_cached()
    assert calls["n"] == 3 and fresh and "100.NDX" in quotes
    assert waits == [1.5, 3.0]  # 第三次才成功，退避 1.5 → 3


def test_cached_backoff_three_retries_then_give_up(tmp_cache, monkeypatch):
    waits: list[float] = []
    monkeypatch.setattr(overseas.time, "sleep", lambda s: waits.append(s))
    calls = {"n": 0}

    def empty(timeout=8.0, pack=None):
        calls["n"] += 1
        return {}

    monkeypatch.setattr(overseas, "fetch_overseas", empty)
    quotes, _at, fresh = fetch_overseas_cached(pack="机器人")
    assert quotes is None and not fresh
    assert calls["n"] == 4  # 首次 + 3 次重试
    assert waits == [1.5, 3.0, 6.0]


def test_cached_total_failure_falls_back_to_stale(tmp_cache, monkeypatch):
    # 先种一份 2 小时前的缓存
    old = {"251.SOX": {"name": "费城半导体指数", "price": 99.0, "change_pct": -1.0, "ts": None}}
    overseas._write_cache("半导体", old)
    import json as _json
    import time as _time

    f = tmp_cache / "overseas-半导体.json"
    raw = _json.loads(f.read_text(encoding="utf-8"))
    raw["fetched_at"] = _time.time() - 7200
    f.write_text(_json.dumps(raw), encoding="utf-8")

    def boom(timeout=8.0, pack=None):
        raise RuntimeError("empty reply")

    monkeypatch.setattr(overseas, "fetch_overseas", boom)
    quotes, at, fresh = fetch_overseas_cached(pack="半导体")
    assert quotes == old and not fresh and at < _time.time() - 7000


def test_cached_total_failure_no_cache(tmp_cache, monkeypatch):
    def boom(timeout=8.0, pack=None):
        raise RuntimeError("empty reply")

    monkeypatch.setattr(overseas, "fetch_overseas", boom)
    quotes, _at, fresh = fetch_overseas_cached(pack="机器人")
    assert quotes is None and not fresh
