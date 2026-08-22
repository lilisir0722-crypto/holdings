from holdings.store import Holding, Store


def test_add_and_list(tmp_path):
    store = Store(tmp_path / "holdings.json")
    item = store.add(
        Holding(kind="股票", code="600519", name="贵州茅台", quantity=100, cost=1500.0)
    )
    assert item.id
    listed = store.list()
    assert len(listed) == 1
    assert listed[0].code == "600519"


def test_delete(tmp_path):
    store = Store(tmp_path / "holdings.json")
    item = store.add(
        Holding(kind="基金", code="510300", name="沪深300ETF", quantity=1000, cost=4.0)
    )
    store.delete(item.id)
    assert store.list() == []


def test_add_with_place(tmp_path):
    store = Store(tmp_path / "holdings.json")
    item = store.add(
        Holding(
            kind="基金",
            code="000198",
            name="天弘余额宝货币",
            quantity=1000,
            cost=1.0,
            place="支付宝",
        )
    )
    listed = store.list()
    assert listed[0].place == "支付宝"
    assert listed[0].id == item.id


def test_update_position_rewrites_qty_and_cost(tmp_path):
    store = Store(tmp_path / "holdings.json")
    item = store.add(
        Holding(kind="基金", code="562590", name="半导", quantity=1000, cost=1.0)
    )
    updated = store.update_position(item.id, quantity=2000, cost=1.1)
    assert updated is not None
    assert updated.quantity == 2000
    assert updated.cost == 1.1
    loaded = store.get(item.id)
    assert loaded is not None
    assert loaded.quantity == 2000
    assert loaded.cost == 1.1


def test_save_and_load_cash(tmp_path):
    from holdings.store import CashBook, Store

    store = Store(tmp_path / "holdings.json")
    store.save_cash(CashBook(yongjinbao=5000, alipay=2000))
    cash = store.load_cash()
    assert cash.known
    assert cash.yongjinbao == 5000
    assert cash.alipay == 2000
    assert cash.total == 7000


def test_cash_unknown_before_save(tmp_path):
    from holdings.store import Store

    store = Store(tmp_path / "holdings.json")
    cash = store.load_cash()
    assert not cash.known
    assert cash.total == 0

