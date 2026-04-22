from datetime import datetime, timezone
from app import get_db
from app.services.inventory_service import adjust_raw_material_qty, add_raw_material
from google.cloud.firestore_v1 import FieldFilter, ArrayUnion

def generate_po_number():
    db = get_db()
    docs = list(db.collection('purchase_orders').order_by('created_at', direction='DESCENDING').limit(1).stream())
    if not docs:
        return "PO-001"
    
    last_doc = docs[0].to_dict()
    last_id = last_doc.get('po_number', '')
    if last_id.startswith('PO-'):
        try:
            num = int(last_id.replace('PO-', ''))
            return f"PO-{num + 1:03d}"
        except:
            pass
    count = len(list(db.collection('purchase_orders').stream()))
    return f"PO-{count + 1:03d}"

def get_all_purchase_orders(date_from=None, date_to=None):
    db = get_db()
    query = db.collection('purchase_orders').order_by('created_at', direction='DESCENDING')
    docs = list(query.stream())
    results = []
    for d in docs:
        entry = {'id': d.id, **d.to_dict()}
        if date_from and entry.get('created_at'):
            dt = entry['created_at'] if isinstance(entry['created_at'], datetime) else entry['created_at']
            if hasattr(dt, 'date') and dt.date() < date_from:
                continue
        if date_to and entry.get('created_at'):
            dt = entry['created_at'] if isinstance(entry['created_at'], datetime) else entry['created_at']
            if hasattr(dt, 'date') and dt.date() > date_to:
                continue
        results.append(entry)
    return results

def add_purchase_order(vendor_name, items):
    db = get_db()
    
    total_cost = sum(float(item['quantity']) * float(item['unit_cost']) for item in items)
    now = datetime.now(timezone.utc)

    po_number = generate_po_number()

    # Create PO with Draft status
    _, doc_ref = db.collection('purchase_orders').add({
        'po_number': po_number,
        'vendor_name': vendor_name,
        'items': items,
        'total_cost': total_cost,
        'status': 'Draft',
        'vendor_invoice_number': '',
        'payment_id': '',
        'created_at': now,
        'updated_at': now,
        'status_history': [{'status': 'Draft', 'timestamp': now.isoformat()}],
    })

    return doc_ref.id

def mark_po_sent(po_id):
    db = get_db()
    now = datetime.now(timezone.utc)
    db.collection('purchase_orders').document(po_id).update({
        'status': 'Sent',
        'updated_at': now,
        'status_history': ArrayUnion([{'status': 'Sent', 'timestamp': now.isoformat()}])
    })

def mark_po_received(po_id):
    db = get_db()
    
    doc = db.collection('purchase_orders').document(po_id).get()
    if not doc.exists:
        return False
    data = doc.to_dict()
    
    if data.get('status') in ['Received', 'Paid']:
        return False
        
    now = datetime.now(timezone.utc)
    db.collection('purchase_orders').document(po_id).update({
        'status': 'Received',
        'updated_at': now,
        'status_history': ArrayUnion([{'status': 'Received', 'timestamp': now.isoformat()}])
    })
    
    # Increment inventory
    po_number = data.get('po_number', po_id)
    reason = f"PO {po_number} Received"
    
    items = data.get('items', [])
    if not items and data.get('item'):
        items = [{'item': data.get('item'), 'quantity': data.get('quantity')}]
        
    for it in items:
        item_name = it.get('item')
        qty = float(it.get('quantity', 0))
        if not adjust_raw_material_qty(item_name, qty, reason=reason):
            add_raw_material(item_name, qty, 'pcs', reason=reason)
        
    return True

def mark_po_paid(po_id, payment_id):
    from app.services.cashbook_service import add_cashbook_entry
    db = get_db()
    
    doc = db.collection('purchase_orders').document(po_id).get()
    if not doc.exists:
        return False
    data = doc.to_dict()
    
    if data.get('status') == 'Paid':
        return False
        
    now = datetime.now(timezone.utc)
    db.collection('purchase_orders').document(po_id).update({
        'status': 'Paid',
        'payment_id': payment_id,
        'updated_at': now,
        'status_history': ArrayUnion([{'status': 'Paid', 'timestamp': now.isoformat()}])
    })
    
    po_number = data.get('po_number', po_id)
    vendor = data.get('vendor_name', 'Unknown')
    
    desc = f"{po_number} Paid to {vendor}"
    if payment_id:
        desc += f" - Txn: {payment_id}"
        
    add_cashbook_entry(
        entry_type='outflow',
        category='Purchase',
        description=desc,
        amount=data.get('total_cost', 0),
        reference_id=po_id,
    )
    
    return True

def cancel_po(po_id):
    db = get_db()
    doc = db.collection('purchase_orders').document(po_id).get()
    if not doc.exists:
        return False
    data = doc.to_dict()
    
    old_status = data.get('status')
    if old_status == 'Cancelled':
        return True
        
    now = datetime.now(timezone.utc)
    db.collection('purchase_orders').document(po_id).update({
        'status': 'Cancelled',
        'updated_at': now,
        'status_history': ArrayUnion([{'status': 'Cancelled', 'timestamp': now.isoformat()}])
    })
    
    # If it was received or paid, reverse inventory
    if old_status in ['Received', 'Paid']:
        po_number = data.get('po_number', po_id)
        reason = f"PO {po_number} Cancelled (Reversal)"
        
        items = data.get('items', [])
        if not items and data.get('item'):
            items = [{'item': data.get('item'), 'quantity': data.get('quantity')}]
            
        for it in items:
            item_name = it.get('item')
            qty = float(it.get('quantity', 0))
            adjust_raw_material_qty(item_name, -qty, reason=reason)
        
        # If it was explicitly paid, reverse the cash outflow by logging a refund (inflow)
        if old_status == 'Paid':
            from app.services.cashbook_service import add_cashbook_entry
            vendor = data.get('vendor_name', 'Unknown')
            add_cashbook_entry(
                entry_type='inflow',
                category='Refund',
                description=f"Refund: {po_number} Cancelled (from {vendor})",
                amount=data.get('total_cost', 0),
                reference_id=po_id,
            )

    return True

def return_po(po_id, refund_amount=0):
    db = get_db()
    doc = db.collection('purchase_orders').document(po_id).get()
    if not doc.exists:
        return False
    data = doc.to_dict()
    
    status = data.get('status')
    if status not in ['Received', 'Paid']:
        return False
        
    now = datetime.now(timezone.utc)
    db.collection('purchase_orders').document(po_id).update({
        'status': 'Returned',
        'updated_at': now,
        'status_history': ArrayUnion([{'status': 'Returned', 'timestamp': now.isoformat()}])
    })
    
    po_number = data.get('po_number', po_id)
    reason = f"PO {po_number} Returned"
    
    items = data.get('items', [])
    if not items and data.get('item'):
        items = [{'item': data.get('item'), 'quantity': data.get('quantity')}]
        
    for it in items:
        item_name = it.get('item')
        qty = float(it.get('quantity', 0))
        adjust_raw_material_qty(item_name, -qty, reason=reason)
        
    if status == 'Paid':
        from app.services.cashbook_service import add_cashbook_entry
        vendor = data.get('vendor_name', 'Unknown')
        refund = float(refund_amount)
        if refund > 0:
            add_cashbook_entry(
                entry_type='inflow',
                category='Refund',
                description=f"Refund: {po_number} Returned (from {vendor})",
                amount=refund,
                reference_id=po_id,
            )

    return True


