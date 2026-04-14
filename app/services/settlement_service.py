from datetime import datetime, timezone
from google.cloud.firestore_v1 import FieldFilter
from app import get_db
from app.services.cashbook_service import add_cashbook_entry

def get_unsettled_orders(platform=None):
    db = get_db()
    query = db.collection('orders').where(filter=FieldFilter("status", "in", ["Shipped", "Delivered"]))
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

def create_payment_settlement(platform, utr_number, amount_received, order_ids, settlement_date, notes):
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

    settlement_doc = {
        'platform': platform,
        'utr_number': utr_number,
        'amount_received': float(amount_received),
        'order_ids': order_ids,
        'settlement_date': settlement_dt,
        'notes': notes,
        'created_at': now
    }
    
    _, doc_ref = db.collection('payment_settlements').add(settlement_doc)
    
    # Update orders to settled
    batch = db.batch()
    for o_id in order_ids:
        order_ref = db.collection('orders').document(o_id)
        batch.update(order_ref, {
            'payment_settled': True,
            'settlement_batch_id': utr_number
        })
    batch.commit()
    
    # Create single cashbook entry
    add_cashbook_entry(
        entry_type='inflow',
        category='Settlement',
        description=f"Platform Payout ({platform}) - UTR: {utr_number}",
        amount=float(amount_received),
        reference_id=doc_ref.id
    )
    
    return doc_ref.id
