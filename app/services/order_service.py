from datetime import datetime, timezone
from app import get_db
from app.services.inventory_service import adjust_ready_stock_qty
from google.cloud.firestore_v1 import FieldFilter


PLATFORMS = ['Amazon', 'Flipkart', 'Meesho', 'Instagram', 'Personal Reference', 'Website']
REVIEWS = ['Done', 'Pending', 'Not Responding']
STATUSES = ['Pending', 'Shipped', 'Delivered', 'RTO', 'Returned', 'Cancelled', 'Settled']
DISPATCHED_STATUSES = ['Shipped', 'Delivered', 'Settled']
RETURNED_STATUSES = ['RTO', 'Returned', 'Customer Return']
CANCELLED_STATUSES = ['Cancelled']
TERMINAL_STATUSES = ['Cancelled', 'Settled', 'Returned', 'RTO']

def get_stock_deltas(status):
    """Returns (qty_delta, reserved_delta) based on order status."""
    if status in DISPATCHED_STATUSES:
        return (-1, 0) # physical stock leaves
    if status in RETURNED_STATUSES:
        return (-1, 0) # physical stock stays deducted (due to potential damages)
    if status in CANCELLED_STATUSES:
        return (0, 0) # neither physical nor reserved
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
    db = get_db()
    now = datetime.now(timezone.utc)

    order_items = data.get('order_items', [])
    selling_price = sum(float(item.get('price', 0)) * float(item.get('quantity', 1)) for item in order_items)
    
    shipping = max(0, float(data.get('shipping', 0)))
    refund = max(0, float(data.get('refund', 0)))
    tax = max(0, float(data.get('tax', 0)))
    marketplace_fee = max(0, float(data.get('marketplace_fee', 0)))
    
    status = data.get('status', 'Pending')
    if status in CANCELLED_STATUSES:
        bank_settlement = 0.0
    else:
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
        'order_items': order_items,
        'platform': data.get('platform', ''),
        'selling_price': selling_price,
        'shipping': shipping,
        'refund': refund,
        'tax': tax,
        'marketplace_fee': marketplace_fee,
        'bank_settlement': bank_settlement,
        'status': status,
        'reviews': data.get('reviews', ''),
        'created_at': now,
    }

    _, doc_ref = db.collection('orders').add(order)

    # Adjust stock based on status for each item
    for item in order_items:
        product = item.get('product', '')
        color = item.get('color', '')
        qty = float(item.get('quantity', 1))
        
        if product:
            qty_delta, res_delta = get_stock_deltas(status)
            if qty_delta != 0 or res_delta != 0:
                o_id = data.get('order_id')
                label = f"Order {o_id} " if o_id else "Order "
                reason = f"{label}logged ({status})"
                adjust_ready_stock_qty(product, color, qty_delta * qty, res_delta * qty, reason=reason, ref_id=doc_ref.id)

    # Cashbook entry is now exclusively handled by the Payment Settlement process

    return doc_ref.id


def update_order(doc_id, data):
    db = get_db()
    
    doc = db.collection('orders').document(doc_id).get()
    if not doc.exists:
        return
    old_data = doc.to_dict()
    
    update_data = {}
    for field in ['order_id', 'customer', 'number', 'platform', 'status', 'reviews']:
        if field in data:
            update_data[field] = data[field]
            
    if 'order_items' in data:
        update_data['order_items'] = data['order_items']
        update_data['selling_price'] = sum(float(item.get('price', 0)) * float(item.get('quantity', 1)) for item in data['order_items'])

    for field in ['shipping', 'refund', 'tax', 'marketplace_fee']:
        if field in data:
            update_data[field] = max(0, float(data[field])) if data[field] else 0

    if any(f in data for f in ['order_items', 'shipping', 'refund', 'tax', 'marketplace_fee', 'status']):
        new_status = update_data.get('status', old_data.get('status', 'Pending'))
        if new_status in CANCELLED_STATUSES:
            update_data['bank_settlement'] = 0.0
        else:
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


    old_status = old_data.get('status', 'Pending')
    old_items = old_data.get('order_items', [])
    new_status = update_data.get('status', old_status)
    new_items = update_data.get('order_items', old_items)
    
    old_items_sig = [(i.get('product'), i.get('color'), i.get('quantity')) for i in old_items]
    new_items_sig = [(i.get('product'), i.get('color'), i.get('quantity')) for i in new_items]
    
    if old_status != new_status or old_items_sig != new_items_sig:
        old_qty_d, old_res_d = get_stock_deltas(old_status)
        for item in old_items:
            prod = item.get('product')
            qty = float(item.get('quantity', 1))
            if prod and (old_qty_d != 0 or old_res_d != 0):
                adjust_ready_stock_qty(prod, item.get('color', ''), -old_qty_d * qty, -old_res_d * qty, reason=f"Update reversal ({old_status})", ref_id=doc_id)

        new_qty_d, new_res_d = get_stock_deltas(new_status)
        for item in new_items:
            prod = item.get('product')
            qty = float(item.get('quantity', 1))
            if prod and (new_qty_d != 0 or new_res_d != 0):
                adjust_ready_stock_qty(prod, item.get('color', ''), new_qty_d * qty, new_res_d * qty, reason=f"Update apply ({new_status})", ref_id=doc_id)


def delete_order(doc_id):
    db = get_db()
    doc = db.collection('orders').document(doc_id).get()
    if not doc.exists:
        return False
    data = doc.to_dict()
    
    if data.get('order_items'):
        old_qty_delta, old_res_delta = get_stock_deltas(data.get('status', 'Pending'))
        for item in data['order_items']:
            prod = item.get('product')
            qty = float(item.get('quantity', 1))
            if prod and (old_qty_delta != 0 or old_res_delta != 0):
                o_id = data.get('order_id')
                label = f"Order {o_id} " if o_id else "Order "
                reason = f"{label}deleted (reversed {data.get('status', 'Pending')})"
                adjust_ready_stock_qty(prod, item.get('color', ''), -old_qty_delta * qty, -old_res_delta * qty, reason=reason, ref_id=doc_id)
                
    db.collection('orders').document(doc_id).delete()
    return True
