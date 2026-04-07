from datetime import datetime, timezone
from app import get_db
from app.services.inventory_service import adjust_ready_stock_qty
from google.cloud.firestore_v1 import FieldFilter


PLATFORMS = ['Amazon', 'Flipkart', 'Meesho', 'Instagram', 'Personal Reference', 'Website']
REVIEWS = ['DONE', 'Pending', 'Not esponding']
STATUSES = ['Pending', 'Shipped', 'Delivered', 'RTO', 'Customer Return', 'Exchange']
DISPATCHED_STATUSES = ['Shipped', 'Delivered']
RETURNED_STATUSES = ['RTO', 'Customer Return']

def get_stock_deltas(status):
    """Returns (qty_delta, reserved_delta) based on order status."""
    if status in DISPATCHED_STATUSES:
        return (-1, 0) # physical stock leaves
    if status in RETURNED_STATUSES:
        return (0, 0) # no effect relative to baseline (returns to basic stock)
    return (0, 1) # pending, reserved


def get_all_orders(date_from=None, date_to=None, platform=None, status=None):
    db = get_db()
    query = db.collection('orders').order_by('date', direction='DESCENDING')
    docs = list(query.stream())
    results = []
    for d in docs:
        entry = {'id': d.id, **d.to_dict()}
        if date_from and entry.get('date'):
            dt = entry['date']
            if hasattr(dt, 'date') and dt.date() < date_from:
                continue
        if date_to and entry.get('date'):
            dt = entry['date']
            if hasattr(dt, 'date') and dt.date() > date_to:
                continue
        if platform and entry.get('platform') != platform:
            continue
        if status and entry.get('status') != status:
            continue
        results.append(entry)
    return results


def add_order(data):
    from app.services.cashbook_service import add_cashbook_entry

    db = get_db()
    now = datetime.now(timezone.utc)

    selling_price = float(data.get('selling_price', 0))
    shipping = float(data.get('shipping', 0))
    refund = float(data.get('refund', 0))
    tax = float(data.get('tax', 0))
    marketplace_fee = float(data.get('marketplace_fee', 0))
    bank_settlement = selling_price - shipping - refund - tax - marketplace_fee

    order_date = data.get('date')
    if order_date:
        try:
            order_date = datetime.strptime(order_date, '%Y-%m-%d').replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            order_date = now
    else:
        order_date = now

    order = {
        'date': order_date,
        'order_id': data.get('order_id', ''),
        'customer': data.get('customer', ''),
        'number': data.get('number', ''),
        'product': data.get('product', ''),
        'color': data.get('color', ''),
        'platform': data.get('platform', ''),
        'selling_price': selling_price,
        'shipping': shipping,
        'refund': refund,
        'tax': tax,
        'marketplace_fee': marketplace_fee,
        'bank_settlement': bank_settlement,
        'status': data.get('status', 'Pending'),
        'reviews': data.get('reviews', ''),
        'created_at': now,
    }

    _, doc_ref = db.collection('orders').add(order)

    # Adjust stock based on status
    product = data.get('product', '')
    color = data.get('color', '')
    status = data.get('status', 'Pending')
    if product:
        qty_delta, res_delta = get_stock_deltas(status)
        if qty_delta != 0 or res_delta != 0:
            reason = f"Order logged ({status})"
            adjust_ready_stock_qty(product, color, qty_delta, res_delta, reason=reason, ref_id=doc_ref.id)

    # Log cash inflow (use bank_settlement as the actual money received)
    if bank_settlement > 0:
        add_cashbook_entry(
            entry_type='inflow',
            category='Sale',
            description=f'Order {data.get("order_id", "")} — {product} ({data.get("platform", "")})',
            amount=bank_settlement,
            reference_id=doc_ref.id,
        )

    return doc_ref.id


def update_order(doc_id, data):
    db = get_db()
    
    # Fetch old order data to allow stock recalcs
    doc = db.collection('orders').document(doc_id).get()
    if not doc.exists:
        return
    old_data = doc.to_dict()
    
    update_data = {}
    for field in ['order_id', 'customer', 'number', 'product', 'color',
                  'platform', 'status', 'reviews']:
        if field in data:
            update_data[field] = data[field]

    for field in ['selling_price', 'shipping', 'refund', 'tax', 'marketplace_fee']:
        if field in data:
            update_data[field] = float(data[field]) if data[field] else 0

    # Recalculate bank settlement if price fields changed
    if any(f in data for f in ['selling_price', 'shipping', 'refund', 'tax', 'marketplace_fee']):
        sp = update_data.get('selling_price', old_data.get('selling_price', 0))
        sh = update_data.get('shipping', old_data.get('shipping', 0))
        rf = update_data.get('refund', old_data.get('refund', 0))
        tx = update_data.get('tax', old_data.get('tax', 0))
        mf = update_data.get('marketplace_fee', old_data.get('marketplace_fee', 0))
        update_data['bank_settlement'] = sp - sh - rf - tx - mf

    if 'date' in data and data['date']:
        try:
            update_data['date'] = datetime.strptime(data['date'], '%Y-%m-%d').replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            pass

    update_data['updated_at'] = datetime.now(timezone.utc)
    db.collection('orders').document(doc_id).update(update_data)

    # Adjust stock if product, color, or status changed
    old_product = old_data.get('product', '')
    old_color = old_data.get('color', '')
    old_status = old_data.get('status', 'Pending')
    
    new_product = update_data.get('product', old_product)
    new_color = update_data.get('color', old_color)
    new_status = update_data.get('status', old_status)
    
    # Reverse old stock logic
    if old_product:
        old_qty_delta, old_res_delta = get_stock_deltas(old_status)
        if old_qty_delta != 0 or old_res_delta != 0:
            reason = f"Order state transition (reversing {old_status})"
            adjust_ready_stock_qty(old_product, old_color, -old_qty_delta, -old_res_delta, reason=reason, ref_id=doc_id)
            
    # Apply new stock logic
    if new_product:
        new_qty_delta, new_res_delta = get_stock_deltas(new_status)
        if new_qty_delta != 0 or new_res_delta != 0:
            reason = f"Order state transition (applying {new_status})"
            adjust_ready_stock_qty(new_product, new_color, new_qty_delta, new_res_delta, reason=reason, ref_id=doc_id)


def delete_order(doc_id):
    db = get_db()
    doc = db.collection('orders').document(doc_id).get()
    if not doc.exists:
        return False
    data = doc.to_dict()
    # Reverse stock deduction or reservation
    if data.get('product'):
        old_qty_delta, old_res_delta = get_stock_deltas(data.get('status', 'Pending'))
        if old_qty_delta != 0 or old_res_delta != 0:
            reason = f"Order deleted (reversed {data.get('status', 'Pending')})"
            adjust_ready_stock_qty(data['product'], data.get('color', ''), -old_qty_delta, -old_res_delta, reason=reason, ref_id=doc_id)
    # Delete linked cashbook
    _delete_cashbook_by_ref(doc_id)
    db.collection('orders').document(doc_id).delete()
    return True


def _delete_cashbook_by_ref(ref_id):
    db = get_db()
    docs = db.collection('cashbook').where(
        filter=FieldFilter('reference_id', '==', ref_id)
    ).stream()
    for d in docs:
        db.collection('cashbook').document(d.id).delete()
