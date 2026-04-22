from datetime import datetime, timezone
from app import get_db
from app.services.inventory_service import adjust_raw_material_qty, add_raw_material
from google.cloud.firestore_v1 import FieldFilter


def get_all_purchases(date_from=None, date_to=None):
    db = get_db()
    query = db.collection('purchases').order_by('date', direction='DESCENDING')
    docs = list(query.stream())
    results = []
    for d in docs:
        entry = {'id': d.id, **d.to_dict()}
        if date_from and entry.get('date'):
            dt = entry['date'] if isinstance(entry['date'], datetime) else entry['date']
            if hasattr(dt, 'date') and dt.date() < date_from:
                continue
        if date_to and entry.get('date'):
            dt = entry['date'] if isinstance(entry['date'], datetime) else entry['date']
            if hasattr(dt, 'date') and dt.date() > date_to:
                continue
        results.append(entry)
    return results


def add_purchase(vendor_name, item, quantity, unit_cost, notes=''):
    from app.services.cashbook_service import add_cashbook_entry

    db = get_db()
    quantity = float(quantity)
    unit_cost = float(unit_cost)
    total_cost = quantity * unit_cost
    now = datetime.now(timezone.utc)

    # 1. Create purchase record
    _, doc_ref = db.collection('purchases').add({
        'date': now,
        'vendor_name': vendor_name,
        'item': item,
        'quantity': quantity,
        'unit_cost': unit_cost,
        'total_cost': total_cost,
        'notes': notes,
        'created_at': now,
    })

    # 2. Increase raw material inventory
    reason = f"Purchased from {vendor_name}"
    if not adjust_raw_material_qty(item, quantity, reason=reason):
        add_raw_material(item, quantity, 'pcs', unit_cost, reason=reason)

    # 3. Log cash outflow
    add_cashbook_entry(
        entry_type='outflow',
        category='Purchase',
        description=f'Purchase from {vendor_name} — {item} x{quantity}',
        amount=total_cost,
        reference_id=doc_ref.id,
    )
    return doc_ref.id


def delete_purchase(doc_id):
    db = get_db()
    doc = db.collection('purchases').document(doc_id).get()
    if not doc.exists:
        return False
    data = doc.to_dict()
    # Reverse inventory increase
    reason = "Reversed Purchase (deleted)"
    adjust_raw_material_qty(data['item'], -data['quantity'], reason=reason)
    # Delete linked cashbook entry
    _delete_cashbook_by_ref(doc_id)
    # Delete purchase
    db.collection('purchases').document(doc_id).delete()
    return True


def _delete_cashbook_by_ref(ref_id):
    db = get_db()
    docs = db.collection('cashbook').where(
        filter=FieldFilter('reference_id', '==', ref_id)
    ).stream()
    for d in docs:
        db.collection('cashbook').document(d.id).delete()
