from datetime import datetime, timezone
from google.cloud.firestore_v1 import FieldFilter
from app import get_db


# ── Inventory Logs ─────────────────────────────────────────────

def log_inventory_transaction(item_type, item_name, color, delta, reason, reference_id=''):
    """Log an IN/OUT movement. delta > 0 is IN, delta < 0 is OUT."""
    try:
        f_delta = float(delta or 0)
    except (ValueError, TypeError):
        f_delta = 0.0
        
    if f_delta == 0:
        return
    db = get_db()
    db.collection('inventory_log').add({
        'date': datetime.now(timezone.utc),
        'item_type': item_type,  # 'Raw Material' or 'Ready Stock'
        'item_name': item_name,
        'color': color,
        'delta': f_delta,
        'reason': reason,
        'reference_id': reference_id
    })

def get_inventory_logs(limit=100):
    db = get_db()
    docs = db.collection('inventory_log').order_by('date', direction='DESCENDING').limit(limit).stream()
    return [{'id': d.id, **d.to_dict()} for d in docs]

def get_product_inventory_logs(name, color=None, limit=100):
    db = get_db()
    query = db.collection('inventory_log').where(filter=FieldFilter('item_name', '==', name))
    if color:
        query = query.where(filter=FieldFilter('color', '==', color))
    
    docs = query.order_by('date', direction='DESCENDING').limit(limit).stream()
    return [{'id': d.id, **d.to_dict()} for d in docs]

# ── Raw Materials ──────────────────────────────────────────────

def get_all_raw_materials():
    db = get_db()
    docs = db.collection('raw_materials').order_by('name').stream()
    materials = [{'id': d.id, **d.to_dict()} for d in docs]

    # Pre-fetch POs to calculate moving average cost
    po_docs = db.collection('purchase_orders').where(filter=FieldFilter('status', 'in', ['Received', 'Paid'])).stream()
    pos = [d.to_dict() for d in po_docs]

    for m in materials:
        name = m.get('name', '').lower()
        mat_pos = [po for po in pos if po.get('item', '').lower() == name]
        
        total_invested = sum(po.get('total_cost', 0) for po in mat_pos)
        total_qty_purchased = sum(po.get('quantity', 0) for po in mat_pos)
        
        avg_price = total_invested / total_qty_purchased if total_qty_purchased > 0 else 0
        m['calc_price'] = avg_price
        m['calc_total_value'] = avg_price * float(m.get('quantity', 0))

    return materials


def add_raw_material(name, quantity, unit, reason='Manual Add'):
    db = get_db()
    qty = float(quantity or 0)
    db.collection('raw_materials').add({
        'name': name,
        'quantity': qty,
        'unit': unit,
        'updated_at': datetime.now(timezone.utc),
    })
    log_inventory_transaction('Raw Material', name, '', qty, reason)


def update_raw_material(doc_id, data):
    db = get_db()
    if 'quantity' in data:
        data['quantity'] = int(float(data['quantity'] or 0))
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
        current = int(float(doc.to_dict().get('quantity', 0)))
        adjusted_delta = int(float(delta))
        new_qty = max(0, current + adjusted_delta)
        db.collection('raw_materials').document(doc.id).update({
            'quantity': new_qty,
            'updated_at': datetime.now(timezone.utc),
        })
        log_inventory_transaction('Raw Material', name, '', adjusted_delta, reason, ref_id)
        return True
    return False


# ── Ready Stock ────────────────────────────────────────────────

def get_all_ready_stock():
    db = get_db()
    docs = db.collection('ready_stock').order_by('name').stream()
    return [{'id': d.id, **d.to_dict()} for d in docs]


def get_ready_stock_grouped():
    """
    Returns a list of parent items, each with an optional 'variants' list.
    Parents with variants get quantity = sum of variant quantities.
    Simple items (no variants) work unchanged.
    """
    db = get_db()
    all_docs = [{'id': d.id, **d.to_dict()} for d in db.collection('ready_stock').order_by('name').stream()]

    # Normalise every doc so Jinja dot-access never fails
    for doc in all_docs:
        doc.setdefault('quantity', 0)
        doc.setdefault('reserved_quantity', 0)
        doc.setdefault('cost_price', 0)
        doc.setdefault('color', '')
        doc.setdefault('name', '')

    parents = []
    variants_by_parent = {}

    for doc in all_docs:
        if doc.get('parent_id'):
            pid = doc['parent_id']
            variants_by_parent.setdefault(pid, []).append(doc)
        else:
            parents.append(doc)

    for parent in parents:
        children = variants_by_parent.get(parent['id'], [])
        if children:
            parent['variants'] = children
            parent['quantity'] = sum(v.get('quantity', 0) for v in children)
            parent['reserved_quantity'] = sum(v.get('reserved_quantity', 0) for v in children)
        else:
            parent['variants'] = []

    return parents


def add_ready_stock(name, color, quantity, cost_price, reason='Manual Add'):
    db = get_db()
    db.collection('ready_stock').add({
        'name': name,
        'color': color,
        'quantity': float(quantity or 0),
        'reserved_quantity': 0,
        'cost_price': float(cost_price or 0),
        'updated_at': datetime.now(timezone.utc),
    })
    log_inventory_transaction('Ready Stock', name, color, quantity, reason)


def update_ready_stock(doc_id, data):
    db = get_db()
    doc_ref = db.collection('ready_stock').document(doc_id)
    doc = doc_ref.get()
    if not doc.exists:
        return False

    # Strip quantity if somehow submitted — all quantity changes go via adjust_ready_stock_qty
    data.pop('quantity', None)

    data['updated_at'] = datetime.now(timezone.utc)
    doc_ref.update(data)
    return True


def delete_ready_stock(doc_id):
    db = get_db()
    db.collection('ready_stock').document(doc_id).delete()


def add_ready_stock_variant(parent_id, parent_name, variant_name, quantity):
    """Add a colour/variant child under an existing parent product."""
    db = get_db()
    qty = int(float(quantity or 0))
    db.collection('ready_stock').add({
        'parent_id': parent_id,
        'name': parent_name,
        'color': variant_name,
        'quantity': qty,
        'reserved_quantity': 0,
        'updated_at': datetime.now(timezone.utc),
    })
    log_inventory_transaction('Ready Stock', parent_name, variant_name, qty, 'Variant Added')


def adjust_ready_stock_qty(name, color, delta=0, reserved_delta=0, reason='Manual Adjustment', ref_id=''):
    """Adjust ready stock quantity by product name + color.
    If color is provided and a matching variant doc exists, targets that variant.
    Otherwise falls back to a parent/simple doc matching by name only.
    """
    db = get_db()
    query = db.collection('ready_stock').where(filter=FieldFilter('name', '==', name))
    if color:
        query = query.where(filter=FieldFilter('color', '==', color))
    docs = list(query.limit(1).stream())
    if not docs and color:
        # Fallback: try matching just by name (simple item with no color field)
        docs = list(
            db.collection('ready_stock')
            .where(filter=FieldFilter('name', '==', name))
            .limit(1).stream()
        )
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

def produce_item(raw_items, product_name, product_color, produce_qty, reason=''):
    """
    Deduct raw materials and add to ready stock.
    raw_items: list of dicts [{name, quantity_used}, ...]
    """
    res_suffix = f" — {reason}" if reason else ""
    for item in raw_items:
        adjust_raw_material_qty(item['name'], -float(item['quantity_used']), reason=f'Used for producing {product_name}{res_suffix}')

    if not adjust_ready_stock_qty(product_name, product_color, float(produce_qty), reason=f'Production{res_suffix}'):
        add_ready_stock(product_name, product_color, float(produce_qty), 0, reason=f'Production{res_suffix}')
