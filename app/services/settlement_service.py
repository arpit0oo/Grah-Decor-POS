from datetime import datetime, timezone
from google.cloud.firestore_v1 import FieldFilter
from app import get_db
from app.services.cashbook_service import add_cashbook_entry
from app.services.inventory_service import adjust_ready_stock_qty


def get_unsettled_orders(platform=None):
    db = get_db()
    query = db.collection('orders').where(filter=FieldFilter("status", "==", "Delivered"))
    if platform:
        query = query.where(filter=FieldFilter("platform", "==", platform))
        
    docs = list(query.stream())
    results = []
    for d in docs:
        entry = {'id': d.id, **d.to_dict()}
        if not entry.get('payment_settled'):
            results.append(entry)
            
    # Sort locally by date desc
    results.sort(key=lambda x: x.get('date') or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return results


def create_payment_settlement(platform, utr_number, amount_received, order_ids, settlement_date, notes, platform_deductions=0):
    """Batch-settle selected orders: save snapshot to settlement_batches, mark orders as Settled, log cashbook inflow."""
    if not order_ids:
        return None
        
    db = get_db()
    now = datetime.now(timezone.utc)
    
    if settlement_date:
        try:
            settlement_dt = datetime.strptime(settlement_date, '%Y-%m-%d').replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            settlement_dt = now
    else:
        settlement_dt = now

    # Build order snapshots for the batch log
    orders_snapshot = []
    for o_id in order_ids:
        doc = db.collection('orders').document(o_id).get()
        if doc.exists:
            data = doc.to_dict()
            orders_snapshot.append({
                'doc_id':          o_id,
                'order_id':        data.get('order_id', ''),
                'customer':        data.get('customer', ''),
                'platform':        data.get('platform', ''),
                'selling_price':   data.get('selling_price', 0),
                'bank_settlement': data.get('bank_settlement', 0),
            })

    gross_amount = float(amount_received)
    deductions   = float(platform_deductions) if platform_deductions else 0.0

    batch_doc = {
        'platform':            platform,
        'utr_number':          utr_number,
        'amount_received':     gross_amount,
        'platform_deductions': deductions,
        'order_count':         len(order_ids),
        'order_ids':           order_ids,
        'orders_snapshot':     orders_snapshot,
        'settlement_date':     settlement_dt,
        'notes':               notes,
        'created_at':          now,
    }
    
    _, doc_ref = db.collection('settlement_batches').add(batch_doc)
    
    # Update orders: mark as Settled (terminal)
    batch = db.batch()
    for o_id in order_ids:
        order_ref = db.collection('orders').document(o_id)
        # Read existing history for this order
        snap = order_ref.get()
        history = snap.to_dict().get('status_history', []) if snap.exists else []
        history.append({'status': 'Settled', 'timestamp': now.isoformat()})
        batch.update(order_ref, {
            'payment_settled': True,
            'settlement_batch_id': utr_number,
            'status': 'Settled',
            'status_history': history,
            'updated_at': now,
        })
    batch.commit()
    
    # Cashbook entry — log the actual received amount as-is (source of truth)
    add_cashbook_entry(
        entry_type='inflow',
        category='Settlement',
        description=f"Platform Payout ({platform}) - UTR: {utr_number}" + (f" | Penalty tracked: ₹{deductions:.0f}" if deductions else ""),
        amount=gross_amount,
        reference_id=doc_ref.id
    )
    
    return doc_ref.id


def get_settlement_batches():
    """Fetch all settlement batch logs, newest first."""
    db = get_db()
    docs = db.collection('settlement_batches').order_by('created_at', direction='DESCENDING').stream()
    results = []
    for d in docs:
        entry = {'id': d.id, **d.to_dict()}
        # Safely expose orders_snapshot avoiding dict.items() collision
        entry['order_lines'] = entry.pop('orders_snapshot', [])
        results.append(entry)
    return results


def process_order_return(order_id, return_type, penalty_amount, item_condition):
    """
    Process a return/RTO for an order.
    - return_type: 'rto' or 'customer_return'
    - penalty_amount: float (only for customer_return)
    - item_condition: 'restock' or 'damaged'
    Sets order to terminal status (RTO or Returned).
    If restock, adds items back to ready_stock.
    """
    db = get_db()
    now = datetime.now(timezone.utc)
    
    doc = db.collection('orders').document(order_id).get()
    if not doc.exists:
        return False
    
    order_data = doc.to_dict()
    
    # Determine new status
    new_status = 'RTO' if return_type == 'rto' else 'Returned'
    
    update = {
        'status':         new_status,
        'return_type':    return_type,
        'item_condition': item_condition,
        'bank_settlement': 0.0,
        'updated_at':     now,
    }
    
    if return_type == 'customer_return' and penalty_amount:
        update['penalty_amount'] = float(penalty_amount)

    # Append to status_history
    existing_history = order_data.get('status_history', [])
    existing_history.append({'status': new_status, 'timestamp': now.isoformat()})
    update['status_history'] = existing_history

    db.collection('orders').document(order_id).update(update)
    
    # Restock items if good condition
    if item_condition == 'restock':
        order_items = order_data.get('order_items', [])
        o_id = order_data.get('order_id', '')
        for item in order_items:
            product = item.get('product', '')
            color = item.get('color', '')
            qty = float(item.get('quantity', 1))
            if product:
                label = f"Order {o_id} " if o_id else "Order "
                reason = f"{label}returned - restocked ({new_status})"
                adjust_ready_stock_qty(product, color, qty, 0, reason=reason, ref_id=order_id)
    
    return True


def get_returned_orders():
    """Fetch all orders with status RTO or Returned, newest first."""
    db = get_db()
    docs = db.collection('orders').where(
        filter=FieldFilter("status", "in", ["RTO", "Returned"])
    ).stream()
    results = []
    for d in docs:
        entry = {'id': d.id, **d.to_dict()}
        results.append(entry)
    results.sort(
        key=lambda x: x.get('updated_at') or x.get('created_at') or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True
    )
    return results


def delete_settlement_batch(batch_id):
    """
    Reverse a settlement batch:
    1. Revert all orders to 'Delivered' status
    2. Delete the linked cashbook entry
    3. Delete the batch document
    """
    db = get_db()
    batch_ref = db.collection('settlement_batches').document(batch_id)
    doc = batch_ref.get()
    
    if not doc.exists:
        return False
        
    data = doc.to_dict()
    order_ids = data.get('order_ids', [])
    
    # 1. Revert orders status
    batch = db.batch()
    now = datetime.now(timezone.utc)
    for o_id in order_ids:
        order_ref = db.collection('orders').document(o_id)
        snap = order_ref.get()
        if snap.exists:
            history = snap.to_dict().get('status_history', [])
            history.append({'status': 'Delivered', 'timestamp': now.isoformat()})
            batch.update(order_ref, {
                'payment_settled': False,
                'settlement_batch_id': '',
                'status': 'Delivered',
                'status_history': history,
                'updated_at': now
            })
    batch.commit()
    
    # 2. Delete linked cashbook entry
    cashbook_docs = db.collection('cashbook').where(filter=FieldFilter('reference_id', '==', batch_id)).stream()
    for c_doc in cashbook_docs:
        db.collection('cashbook').document(c_doc.id).delete()
        
    # 3. Delete the batch document
    batch_ref.delete()
    return True
