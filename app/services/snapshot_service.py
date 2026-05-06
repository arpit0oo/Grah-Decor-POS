from datetime import datetime, timezone
from app import get_db
from app.services.inventory_service import log_inventory_transaction


# ── Helpers ────────────────────────────────────────────────────────────────────

def _fmt_date(dt):
    """Format a UTC datetime or Firestore Timestamp as '27 Apr 2026'."""
    if dt is None:
        return '—'
    if hasattr(dt, 'strftime'):
        return dt.strftime('%d %b %Y')
    return str(dt)


def _period_label(period_start_dt, period_end_dt=None):
    """Build a human label like '27 Apr 2026 → …' or '27 Apr 2026 → 30 Apr 2026'."""
    start = _fmt_date(period_start_dt)
    if period_end_dt:
        return f'{start} → {_fmt_date(period_end_dt)}'
    return f'{start} → …'


# ── Queries ────────────────────────────────────────────────────────────────────

def get_all_snapshots():
    """Return all period snapshot docs, newest first (by period_start desc)."""
    db = get_db()
    docs = db.collection('monthly_snapshots').stream()
    results = [{'id': d.id, **d.to_dict()} for d in docs]
    # Sort in Python — avoids needing a Firestore composite index
    results.sort(key=lambda s: s.get('period_start') or '', reverse=True)
    return results


def get_open_snapshot():
    """Return the single currently-open period, or None."""
    db = get_db()
    docs = list(
        db.collection('monthly_snapshots')
        .where('status', '==', 'open')
        .limit(1)
        .stream()
    )
    if docs:
        return {'id': docs[0].id, **docs[0].to_dict()}
    return None


def get_snapshot_by_id(doc_id):
    """Return a snapshot doc by its Firestore document ID."""
    db = get_db()
    doc = db.collection('monthly_snapshots').document(doc_id).get()
    if doc.exists:
        return {'id': doc.id, **doc.to_dict()}
    return None


def get_latest_closed_snapshot():
    """Return the most-recently closed period, or None (used for carry-forward)."""
    db = get_db()
    docs = list(
        db.collection('monthly_snapshots')
        .where('status', '==', 'closed')
        .stream()
    )
    if not docs:
        return None
    # Sort in Python — avoids needing a Firestore composite index
    results = [{'id': d.id, **d.to_dict()} for d in docs]
    results.sort(key=lambda s: s.get('period_start') or '', reverse=True)
    return results[0]


# ── Opening Snapshot ───────────────────────────────────────────────────────────

def take_opening_snapshot():
    """
    Start a new audit period.

    Rules:
    - Only one OPEN period allowed at a time → returns ('already_open', None) if one exists.
    - First-ever period → reads current raw_materials quantities from the system.
    - Subsequent periods → carries forward the previous closing physical counts.
    - Read-only operation: writes nothing to inventory_log.

    Returns ('ok', doc_id) on success, or an error string tuple.
    """
    db = get_db()

    # Guard: only one open period at a time
    if get_open_snapshot():
        return ('already_open', None)

    now = datetime.now(timezone.utc)
    latest_closed = get_latest_closed_snapshot()

    materials = []

    if latest_closed is None:
        # ── First period ever: read live system quantities ──────────────────
        rm_docs = db.collection('raw_materials').order_by('name').stream()
        for d in rm_docs:
            m = d.to_dict()
            materials.append({
                'name':        m.get('name', ''),
                'unit':        m.get('unit', 'pcs'),
                'opening_qty': float(m.get('quantity', 0)),
                'price':       float(m.get('price', 0)),
            })
        source = 'system'
    else:
        # ── Carry forward previous period's physical closing counts ─────────
        closing_materials = (
            latest_closed.get('closing', {}) or {}
        ).get('materials', [])
        # Build a lookup from the previous opening for unit/price
        prev_opening_materials = (
            latest_closed.get('opening', {}) or {}
        ).get('materials', [])
        unit_map  = {m['name']: m.get('unit', 'pcs') for m in prev_opening_materials}
        price_map = {m['name']: m.get('price', 0)    for m in prev_opening_materials}

        for cm in closing_materials:
            name = cm.get('name', '')
            materials.append({
                'name':        name,
                'unit':        unit_map.get(name, 'pcs'),
                'opening_qty': float(cm.get('closing_qty', 0)),
                'price':       float(price_map.get(name, 0)),
            })
        source = 'carry_forward'

    opening = {
        'taken_at':  now,
        'source':    source,
        'materials': materials,
    }

    _, doc_ref = db.collection('monthly_snapshots').add({
        'period_start':  now,
        'period_end':    None,
        'period_label':  _period_label(now),
        'status':        'open',
        'opening':       opening,
        'closing':       None,
        'created_at':    now,
    })

    return ('ok', doc_ref.id)


# ── Closing Snapshot ───────────────────────────────────────────────────────────

def take_closing_snapshot(doc_id, closing_counts):
    """
    Close an open audit period.

    closing_counts: dict  {material_name: physical_count (float)}

    Logic per material:
      system_qty   = current raw_materials[name].quantity
      purchases    = system_qty − opening_qty          (what arrived since opening)
      consumed     = system_qty − physical_closing_qty  (what was used)
      adjustment   = closing_qty − system_qty           (positive → surplus, negative → shrinkage)

    After saving the snapshot document:
      - Updates each material's raw_materials quantity to match the physical count.
      - Writes one inventory_log entry per material (delta = adjustment).

    Returns 'ok' on success, or an error string.
    """
    db = get_db()
    existing = get_snapshot_by_id(doc_id)
    if not existing:
        return 'not_found'
    if not existing.get('opening'):
        return 'no_opening'
    if existing.get('status') == 'closed':
        return 'already_closed'

    now              = datetime.now(timezone.utc)
    opening_materials = existing['opening']['materials']

    # Fetch live raw_materials quantities in one pass
    rm_docs = db.collection('raw_materials').order_by('name').stream()
    system_qty_map = {}  # name → current system qty
    rm_id_map      = {}  # name → firestore doc id
    for d in rm_docs:
        m = d.to_dict()
        name = m.get('name', '')
        system_qty_map[name] = float(m.get('quantity', 0))
        rm_id_map[name]      = d.id

    period_start = existing.get('period_start')
    start_label  = _fmt_date(period_start)
    end_label    = _fmt_date(now)
    audit_reason = f'Stock Audit Closing — {start_label} → {end_label}'

    closing_materials = []
    for m in opening_materials:
        name        = m['name']
        opening_qty = float(m.get('opening_qty', 0))
        system_qty  = system_qty_map.get(name, opening_qty)
        closing_qty = float(closing_counts.get(name, system_qty))

        if closing_qty > system_qty:
            return f'invalid_count:{name}'

        purchases_qty = max(0.0, system_qty - opening_qty)   # net inflow during period
        consumed      = max(0.0, system_qty - closing_qty)   # usage during period
        adjustment    = closing_qty - system_qty              # ± shrinkage / surplus

        closing_materials.append({
            'name':         name,
            'system_qty':   system_qty,
            'closing_qty':  closing_qty,
            'purchases_qty': purchases_qty,
            'consumed':     consumed,
            'adjustment':   adjustment,
        })

    closing = {
        'taken_at':  now,
        'materials': closing_materials,
    }

    # ── 1. Save closing data to Firestore ──────────────────────────────────
    db.collection('monthly_snapshots').document(doc_id).update({
        'closing':      closing,
        'period_end':   now,
        'period_label': _period_label(period_start, now),
        'status':       'closed',
        'updated_at':   now,
    })

    # ── 2. Update raw_materials quantities to match physical count ─────────
    # ── 3. Write inventory_log per material ───────────────────────────────
    for row in closing_materials:
        name        = row['name']
        closing_qty = row['closing_qty']
        adjustment  = row['adjustment']
        rm_id = rm_id_map.get(name)

        if rm_id:
            db.collection('raw_materials').document(rm_id).update({
                'quantity':   closing_qty,
                'updated_at': now,
            })

        # Only log if there is a real quantity change
        if adjustment != 0:
            log_inventory_transaction(
                item_type='Raw Material',
                item_name=name,
                color='',
                delta=adjustment,
                reason=audit_reason,
                reference_id=doc_id,
            )

    return 'ok'
