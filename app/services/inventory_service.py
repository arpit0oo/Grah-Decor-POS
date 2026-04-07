from datetime import datetime, timezone
from google.cloud.firestore_v1 import FieldFilter
from app import get_db


# ── Inventory Logs ─────────────────────────────────────────────

def log_inventory_transaction(item_type, item_name, color, delta, reason, reference_id=''):
    """Log an IN/OUT movement. delta > 0 is IN, delta < 0 is OUT."""
    if delta == 0:
        return
    db = get_db()
    db.collection('inventory_log').add({
        'date': datetime.now(timezone.utc),
        'item_type': item_type,  # 'Raw Material' or 'Ready Stock'
        'item_name': item_name,
        'color': color,
        'delta': float(delta),
        'reason': reason,
        'reference_id': reference_id
    })

def get_inventory_logs(limit=100):
    db = get_db()
    docs = db.collection('inventory_log').order_by('date', direction='DESCENDING').limit(limit).stream()
    return [{'id': d.id, **d.to_dict()} for d in docs]

# ── Raw Materials ──────────────────────────────────────────────

def get_all_raw_materials():
    db = get_db()
    docs = db.collection('raw_materials').order_by('name').stream()
    return [{'id': d.id, **d.to_dict()} for d in docs]


def add_raw_material(name, quantity, unit, price=0, reason='Manual Add'):
    db = get_db()
    db.collection('raw_materials').add({
        'name': name,
        'quantity': float(quantity),
        'unit': unit,
        'price': float(price),
        'updated_at': datetime.now(timezone.utc),
    })
    log_inventory_transaction('Raw Material', name, '', quantity, reason)


def update_raw_material(doc_id, data):
    db = get_db()
    data['updated_at'] = datetime.now(timezone.utc)
    db.collection('raw_materials').document(doc_id).update(data)


def delete_raw_material(doc_id):
    db = get_db()
    db.collection('raw_materials').document(doc_id).delete()


def adjust_raw_material_qty(name, delta, reason='Manual Adjustment', ref_id=''):
    """Increment (positive delta) or decrement (negative delta) quantity by material name."""
    db = get_db()
    docs = list(
        db.collection('raw_materials')
        .where(filter=FieldFilter('name', '==', name))
        .limit(1)
        .stream()
    )
    if docs:
        doc = docs[0]
        current = doc.to_dict().get('quantity', 0)
        new_qty = max(0, current + float(delta))
        db.collection('raw_materials').document(doc.id).update({
            'quantity': new_qty,
            'updated_at': datetime.now(timezone.utc),
        })
        log_inventory_transaction('Raw Material', name, '', delta, reason, ref_id)
        return True
    return False


# ── Ready Stock ────────────────────────────────────────────────

def get_all_ready_stock():
    db = get_db()
    docs = db.collection('ready_stock').order_by('name').stream()
    return [{'id': d.id, **d.to_dict()} for d in docs]


def add_ready_stock(name, color, quantity, cost_price, reason='Manual Add'):
    db = get_db()
    db.collection('ready_stock').add({
        'name': name,
        'color': color,
        'quantity': float(quantity),
        'reserved_quantity': 0,
        'cost_price': float(cost_price),
        'updated_at': datetime.now(timezone.utc),
    })
    log_inventory_transaction('Ready Stock', name, color, quantity, reason)


def update_ready_stock(doc_id, data):
    db = get_db()
    data['updated_at'] = datetime.now(timezone.utc)
    db.collection('ready_stock').document(doc_id).update(data)


def delete_ready_stock(doc_id):
    db = get_db()
    db.collection('ready_stock').document(doc_id).delete()


def adjust_ready_stock_qty(name, color, delta=0, reserved_delta=0, reason='Manual Adjustment', ref_id=''):
    """Adjust ready stock quantity by product name + color."""
    db = get_db()
    query = db.collection('ready_stock').where(filter=FieldFilter('name', '==', name))
    if color:
        query = query.where(filter=FieldFilter('color', '==', color))
    docs = list(query.limit(1).stream())
    if docs:
        doc = docs[0]
        data = doc.to_dict()
        current_qty = data.get('quantity', 0)
        current_reserved = data.get('reserved_quantity', 0)
        
        new_qty = max(0, current_qty + float(delta))
        new_reserved = max(0, current_reserved + float(reserved_delta))
        
        db.collection('ready_stock').document(doc.id).update({
            'quantity': new_qty,
            'reserved_quantity': new_reserved,
            'updated_at': datetime.now(timezone.utc),
        })
        if delta != 0:
            log_inventory_transaction('Ready Stock', name, color, delta, reason, ref_id)
        return True
    return False


# ── Produce ────────────────────────────────────────────────────

def produce_item(raw_items, product_name, product_color, produce_qty):
    """
    Deduct raw materials and add to ready stock.
    raw_items: list of dicts [{name, quantity_used}, ...]
    """
    for item in raw_items:
        adjust_raw_material_qty(item['name'], -float(item['quantity_used']), reason=f'Used for producing {product_name}')

    if not adjust_ready_stock_qty(product_name, product_color, float(produce_qty), reason='Production'):
        add_ready_stock(product_name, product_color, float(produce_qty), 0, reason='Production')
