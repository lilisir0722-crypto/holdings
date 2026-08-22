"""买入流水：每只持仓一份 jsonl，加权平均回写数量和成本。

第一次追加时，若还没有流水，先把当前数量+成本记成「开仓」。
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path

from holdings.store import Holding, Store

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "lots"


def _path(holding_id: str) -> Path:
    return DATA_DIR / f"{holding_id.strip()}.jsonl"


def weighted_position(lots: list[dict]) -> tuple[float, float]:
    qty = 0.0
    value = 0.0
    for rec in lots:
        q = float(rec.get("quantity") or 0)
        p = float(rec.get("price") or 0)
        if q <= 0:
            continue
        qty += q
        value += q * p
    if qty <= 0:
        return 0.0, 0.0
    return qty, value / qty


def load_lots(holding_id: str) -> list[dict]:
    """按时间旧→新。"""
    path = _path(holding_id)
    if not path.exists():
        return []
    out: list[dict] = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(rec, dict):
                out.append(rec)
    return out


def _write_all(holding_id: str, recs: list[dict]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = _path(holding_id)
    tmp = path.with_suffix(".jsonl.tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        for rec in recs:
            fh.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
    tmp.replace(path)


def _append(holding_id: str, rec: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with _path(holding_id).open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")


def _new_lot(*, quantity: float, price: float, kind: str) -> dict:
    now = datetime.now()
    return {
        "id": now.strftime("%Y%m%d%H%M%S") + "-" + uuid.uuid4().hex[:6],
        "ts": now.isoformat(timespec="seconds"),
        "date": now.strftime("%Y-%m-%d"),
        "kind": kind,
        "quantity": quantity,
        "price": price,
    }


def ensure_opening(holding: Holding) -> bool:
    """没有流水且已有仓位时，记下开仓底账。"""
    hid = (holding.id or "").strip()
    if not hid:
        return False
    if load_lots(hid):
        return False
    qty = float(holding.quantity or 0)
    cost = float(holding.cost or 0)
    if qty <= 0:
        return False
    _append(hid, _new_lot(quantity=qty, price=cost, kind="开仓"))
    return True


def _sync(store: Store, holding: Holding) -> Holding:
    qty, cost = weighted_position(load_lots(holding.id))
    updated = store.update_position(holding.id, quantity=qty, cost=cost)
    return updated if updated is not None else holding


def apply_buy(store: Store, holding: Holding, quantity: float, price: float) -> Holding:
    if quantity <= 0 or price <= 0:
        raise ValueError("数量和价格都要大于 0")
    ensure_opening(holding)
    _append(holding.id, _new_lot(quantity=quantity, price=price, kind="追加"))
    return _sync(store, holding)


def apply_delete(store: Store, holding: Holding, lot_id: str) -> Holding:
    recs = [r for r in load_lots(holding.id) if r.get("id") != lot_id]
    _write_all(holding.id, recs)
    return _sync(store, holding)
