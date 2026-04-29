import argparse
import sys
from datetime import datetime, timezone
import firebase_admin
from firebase_admin import credentials, firestore

# Initialize Firebase (assuming same mechanism as app.py or fallback to default)
try:
    from app import create_app
    app = create_app()
    app.app_context().push()
    from app import get_db
    db = get_db()
except Exception as e:
    print("Could not load from app, trying direct firebase_admin init...")
    try:
        cred = credentials.Certificate('serviceAccountKey.json')
        firebase_admin.initialize_app(cred)
        db = firestore.client()
    except Exception as inner_e:
        print("Error initializing Firebase:", inner_e)
        sys.exit(1)


def derive_inventory_status(status):
    mapping = {
        'Received': 'received',
        'Paid': 'received',
        'Returned': 'returned',
        'Cancelled': 'returned',
    }
    return mapping.get(status, 'pending')


def derive_payment_status(status):
    if status == 'Paid':
        return 'paid'
    return 'unpaid'


def migrate_purchase_orders(dry_run=False):
    print(f"Starting PO schema migration... (Dry Run: {dry_run})")
    
    docs = list(db.collection('purchase_orders').stream())
    print(f"Found {len(docs)} Purchase Order(s) to process.")
    
    batch = db.batch()
    batch_count = 0
    total_updated = 0
    BATCH_LIMIT = 400
    
    for doc in docs:
        data = doc.to_dict()
        po_id = doc.id
        po_number = data.get('po_number', po_id)
        
        # Check if already migrated
        if 'inventory_status' in data and 'payment_status' in data and 'balance_due' in data:
            # Maybe check items array as well, but this is a good indicator
            items = data.get('items', [])
            is_migrated = True
            for it in items:
                if 'ordered_qty' not in it:
                    is_migrated = False
                    break
            
            if is_migrated:
                # print(f"[{po_number}] Already migrated. Skipping.")
                continue

        status = data.get('status', '')
        total_cost = float(data.get('total_cost', 0))
        
        # 1. Derive PO-level fields
        inventory_status = data.get('inventory_status', derive_inventory_status(status))
        payment_status = data.get('payment_status', derive_payment_status(status))
        
        amount_paid = data.get('amount_paid')
        if amount_paid is None:
            amount_paid = total_cost if status == 'Paid' else 0.0
        else:
            amount_paid = float(amount_paid)
            
        balance_due = data.get('balance_due')
        if balance_due is None:
            balance_due = total_cost - amount_paid
        else:
            balance_due = float(balance_due)
            
        extra_charges = data.get('extra_charges', [])
        
        # 2. Derive items array
        raw_items = data.get('items', [])
        if not raw_items and data.get('item'):
            raw_items = [{
                'item': data.get('item'),
                'quantity': data.get('quantity', 0),
                'unit_cost': data.get('unit_cost', 0)
            }]
            
        updated_items = []
        for it in raw_items:
            ordered_qty = float(it.get('ordered_qty', it.get('quantity', 0)))
            
            received_qty = float(it.get('received_qty', -1))
            if received_qty == -1:
                if status in ['Received', 'Paid', 'Returned']:
                    received_qty = ordered_qty
                else:
                    received_qty = 0.0
                    
            returned_qty = float(it.get('returned_qty', -1))
            if returned_qty == -1:
                if status == 'Returned':
                    returned_qty = ordered_qty
                else:
                    returned_qty = 0.0
                    
            updated_it = {
                **it,
                'ordered_qty': ordered_qty,
                'received_qty': received_qty,
                'returned_qty': returned_qty,
            }
            updated_items.append(updated_it)
            
        updates = {
            'inventory_status': inventory_status,
            'payment_status': payment_status,
            'amount_paid': amount_paid,
            'balance_due': balance_due,
            'extra_charges': extra_charges,
            'items': updated_items,
        }
        
        # In case legacy item fields exist, we could delete them, 
        # but it's safer to just overwrite / ignore them.
        # We will apply the update:
        
        if dry_run:
            print(f"\n[DRY RUN] Would update PO {po_number} ({po_id}):")
            print(f"  Old Status: {status} | Total: {total_cost}")
            print(f"  New Fields: inventory={inventory_status}, payment={payment_status}, paid={amount_paid}, due={balance_due}")
            print(f"  Items ({len(updated_items)}):")
            for i, it in enumerate(updated_items):
                print(f"    - {it.get('item')}: ord={it['ordered_qty']}, rec={it['received_qty']}, ret={it['returned_qty']}")
        else:
            batch.update(doc.reference, updates)
            batch_count += 1
            total_updated += 1
            
            if batch_count >= BATCH_LIMIT:
                print(f"Committing batch of {batch_count} updates...")
                batch.commit()
                batch = db.batch()
                batch_count = 0
                
    if not dry_run and batch_count > 0:
        print(f"Committing final batch of {batch_count} updates...")
        batch.commit()
        
    print(f"\nMigration complete. Total POs updated: {total_updated}")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Migrate Purchase Orders to the Phase 1+ Schema (Partials).')
    parser.add_argument('--dry-run', action='store_true', help='Print what would change without modifying the database.')
    args = parser.parse_args()
    
    migrate_purchase_orders(dry_run=args.dry_run)
