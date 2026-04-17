from datetime import datetime, timezone
from app import get_db


def get_all_audits():
    """Fetch all stock audit reports, newest first."""
    db = get_db()
    docs = db.collection('stock_audits').order_by('created_at', direction='DESCENDING').stream()
    results = []
    for d in docs:
        entry = {'id': d.id, **d.to_dict()}
        # Normalise timestamp — always expose as 'created_at'
        if not entry.get('created_at') and entry.get('date'):
            entry['created_at'] = entry['date']
        results.append(entry)
    return results


def get_audit_by_id(audit_id):
    """Fetch a single audit document by ID."""
    db = get_db()
    doc = db.collection('stock_audits').document(audit_id).get()
    if doc.exists:
        return {'id': doc.id, **doc.to_dict()}
    return None


def finalize_audit(items_data, notes=''):
    """
    Commit an audit.

    items_data: list of dicts:
        {
          doc_id, name, unit, price (unit_cost),
          system_qty, actual_qty
        }

    For each item:
      - variance  = actual_qty - system_qty   (negative = missing / consumed)
      - utilized  = system_qty - actual_qty   (positive = consumed since last checkpoint)
      - Updates live raw_material quantity to actual_qty
      - Logs to inventory_log

    Saves an immutable snapshot to stock_audits.
    """
    db = get_db()
    now = datetime.now(timezone.utc)

    audit_items = []
    total_utilized_value = 0.0

    for item in items_data:
        opening_stock = float(item.get('opening_stock', 0))
        purchased     = float(item.get('purchased', 0))
        unit_cost     = float(item.get('price', 0))
        utilized      = opening_stock - purchased          # material consumed
        closing_stock = purchased - opening_stock          # difference (variance) 
        utilized_cost = utilized * unit_cost

        total_utilized_value += max(0, utilized_cost)

        audit_items.append({
            'name':          item.get('name', ''),
            'unit':          item.get('unit', 'pcs'),
            'unit_cost':     unit_cost,
            'opening_stock': opening_stock,
            'purchased':     purchased,
            'closing_stock': closing_stock,
            'utilized':      utilized,
            'utilized_cost': utilized_cost,
        })

        # Update live quantity
        doc_id = item.get('doc_id')
        if doc_id:
            from app.services.inventory_service import log_inventory_transaction
            db.collection('raw_materials').document(doc_id).update({
                'quantity':   int(purchased),
                'updated_at': now,
            })
            delta = purchased - opening_stock
            if delta != 0:
                name = item.get('name', '')
                reason = f"Stock Audit adjustment"
                log_inventory_transaction('Raw Material', name, '', delta, reason)

    # Save immutable snapshot — always use created_at as the canonical timestamp
    db.collection('stock_audits').add({
        'date':                 now,       # keep for backward compat
        'created_at':           now,       # strict UTC sort key
        'notes':                notes,
        'total_utilized_value': round(total_utilized_value, 2),
        'item_count':           len(audit_items),
        'items':                audit_items,
    })

    return True
