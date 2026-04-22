from datetime import datetime, timezone
from app import get_db
from app.services.inventory_service import adjust_raw_material_qty, add_raw_material
from google.cloud.firestore_v1 import FieldFilter

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

def add_purchase_order(vendor_name, item, quantity, unit_cost):
    db = get_db()
    quantity = float(quantity)
    unit_cost = float(unit_cost)
    total_cost = quantity * unit_cost
    now = datetime.now(timezone.utc)

    po_number = generate_po_number()

    # Create PO with Draft status
    _, doc_ref = db.collection('purchase_orders').add({
        'po_number': po_number,
        'vendor_name': vendor_name,
        'item': item,
        'quantity': quantity,
        'unit_cost': unit_cost,
        'total_cost': total_cost,
        'status': 'Draft',
        'vendor_invoice_number': '',
        'payment_id': '',
        'created_at': now,
        'updated_at': now,
    })

    return doc_ref.id

def mark_po_sent(po_id):
    db = get_db()
    db.collection('purchase_orders').document(po_id).update({
        'status': 'Sent',
        'updated_at': datetime.now(timezone.utc)
    })

def mark_po_received(po_id):
    db = get_db()
    
    doc = db.collection('purchase_orders').document(po_id).get()
    if not doc.exists:
        return False
    data = doc.to_dict()
    
    if data.get('status') in ['Received', 'Paid']:
        return False
        
    db.collection('purchase_orders').document(po_id).update({
        'status': 'Received',
        'updated_at': datetime.now(timezone.utc)
    })
    
    # Increment inventory
    item = data.get('item')
    quantity = data.get('quantity')
    po_number = data.get('po_number', po_id)
    unit_cost = data.get('unit_cost', 0)
    
    reason = f"PO {po_number} Received"
    if not adjust_raw_material_qty(item, quantity, reason=reason):
        add_raw_material(item, quantity, 'pcs', unit_cost, reason=reason)
        
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
        
    db.collection('purchase_orders').document(po_id).update({
        'status': 'Paid',
        'payment_id': payment_id,
        'updated_at': datetime.now(timezone.utc)
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
        
    db.collection('purchase_orders').document(po_id).update({
        'status': 'Cancelled',
        'updated_at': datetime.now(timezone.utc)
    })
    
    # If it was received or paid, reverse inventory
    if old_status in ['Received', 'Paid']:
        po_number = data.get('po_number', po_id)
        item = data.get('item')
        quantity = data.get('quantity')
        reason = f"PO {po_number} Cancelled (Reversal)"
        adjust_raw_material_qty(item, -quantity, reason=reason)
        
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


