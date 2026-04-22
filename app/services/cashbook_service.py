from datetime import datetime, timezone
from app import get_db


def get_today_transactions():
    """Get all cashbook entries for today."""
    db = get_db()
    now = datetime.now(timezone.utc)
    start = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
    docs = (
        db.collection('cashbook')
        .order_by('date', direction='DESCENDING')
        .stream()
    )
    results = []
    for d in docs:
        entry = {'id': d.id, **d.to_dict()}
        results.append(entry)
    # Filter today's in Python for simplicity
    today_entries = []
    for e in results:
        dt = e.get('date')
        if dt and hasattr(dt, 'date') and dt.date() == now.date():
            today_entries.append(e)
    return today_entries


def get_all_transactions(date_from=None, date_to=None):
    """Get all cashbook entries with optional date filter."""
    db = get_db()
    docs = (
        db.collection('cashbook')
        .order_by('date', direction='DESCENDING')
        .stream()
    )
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
        results.append(entry)
    return results


def get_running_balance():
    """Calculate total balance = sum(inflows) - sum(outflows)."""
    db = get_db()
    docs = db.collection('cashbook').stream()
    balance = 0.0
    for d in docs:
        data = d.to_dict()
        if data.get('type') == 'inflow':
            balance += data.get('amount', 0)
        else:
            balance -= data.get('amount', 0)
    return balance


def add_cashbook_entry(entry_type, category, description, amount, reference_id=''):
    db = get_db()
    now = datetime.now(timezone.utc)
    db.collection('cashbook').add({
        'date': now,
        'type': entry_type,
        'category': category,
        'description': description,
        'amount': float(amount),
        'reference_id': reference_id,
        'created_at': now,
    })
