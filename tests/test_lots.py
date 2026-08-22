from holdings.store import Holding, Store


def test_weighted_position_two_buys():
    from holdings.lots import weighted_position

    qty, cost = weighted_position(
        [
            {"quantity": 1000, "price": 1.0},
            {"quantity": 1000, "price": 1.2},
        ]
    )
    assert qty == 2000
    assert round(cost, 4) == 1.1


def test_add_lot_seeds_opening_then_recalculates(tmp_path, monkeypatch):
    import holdings.lots as lots

    monkeypatch.setattr(lots, "DATA_DIR", tmp_path / "lots")
    store = Store(tmp_path / "holdings.json")
    hit = store.add(Holding(kind="基金", code="562590", name="半导", quantity=1000, cost=1.0))

    out = lots.apply_buy(store, hit, quantity=1000, price=1.2)
    assert out.quantity == 2000
    assert round(out.cost, 4) == 1.1
    recs = lots.load_lots(hit.id)
    assert [r["kind"] for r in recs] == ["开仓", "追加"]
    assert recs[0]["quantity"] == 1000
    assert recs[0]["price"] == 1.0
    assert recs[1]["quantity"] == 1000
    assert recs[1]["price"] == 1.2


def test_delete_lot_recalculates_cost(tmp_path, monkeypatch):
    import holdings.lots as lots

    monkeypatch.setattr(lots, "DATA_DIR", tmp_path / "lots")
    store = Store(tmp_path / "holdings.json")
    hit = store.add(Holding(kind="基金", code="562590", name="半导", quantity=1000, cost=1.0))
    lots.apply_buy(store, hit, quantity=1000, price=1.2)
    recs = lots.load_lots(hit.id)
    extra = recs[-1]
    out = lots.apply_delete(store, hit, extra["id"])
    assert out.quantity == 1000
    assert round(out.cost, 4) == 1.0
    assert [r["kind"] for r in lots.load_lots(hit.id)] == ["开仓"]


def test_apply_buy_rejects_non_positive(tmp_path, monkeypatch):
    import holdings.lots as lots
    import pytest

    monkeypatch.setattr(lots, "DATA_DIR", tmp_path / "lots")
    store = Store(tmp_path / "holdings.json")
    hit = store.add(Holding(kind="基金", code="562590", name="半导", quantity=1000, cost=1.0))
    with pytest.raises(ValueError):
        lots.apply_buy(store, hit, quantity=0, price=1.2)
    with pytest.raises(ValueError):
        lots.apply_buy(store, hit, quantity=100, price=0)
