from datetime import datetime, timezone
from app import get_db
from app.services.inventory_service import adjust_raw_material_qty, add_raw_material
from google.cloud.firestore_v1 import FieldFilter


def generate_purchase_id():
    db = get_db()
    docs = list(db.collection('purchases').order_by('created_at', direction='DESCENDING').limit(1).stream())
    if not docs:
        return "PUR-001"
    
    last_doc = docs[0].to_dict()
    last_id = last_doc.get('purchase_id', '')
    if last_id.startswith('PUR-'):
        try:
            num = int(last_id.replace('PUR-', ''))
            return f"PUR-{num + 1:03d}"
        except:
            pass
    count = len(list(db.collection('purchases').stream()))
    return f"PUR-{count + 1:03d}"

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

    purchase_id = generate_purchase_id()

    # 1. Create purchase record
    _, doc_ref = db.collection('purchases').add({
        'purchase_id': purchase_id,
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
    reason = f"Purchase {purchase_id} from {vendor_name}"
    if not adjust_raw_material_qty(item, quantity, reason=reason):
        add_raw_material(item, quantity, 'pcs', unit_cost, reason=reason)

    # 3. Log cash outflow
    add_cashbook_entry(
        entry_type='outflow',
        category='Purchase',
        description=f'Purchase {purchase_id} from {vendor_name} — {item} x{quantity}',
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
    p_id = data.get('purchase_id', doc_id)
    reason = f"Reversed Purchase {p_id} (deleted)"
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
