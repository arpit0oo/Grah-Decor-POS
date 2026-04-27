from flask import Blueprint, render_template, request, redirect, url_for, flash
from app.services.snapshot_service import (
    get_all_snapshots,
    get_open_snapshot,
    get_snapshot_by_id,
    take_opening_snapshot,
    take_closing_snapshot,
)

snapshots_bp = Blueprint('snapshots', __name__, url_prefix='/snapshots')


# ── List ───────────────────────────────────────────────────────────────────────

@snapshots_bp.route('/')
def snapshots_list():
    snapshots = get_all_snapshots()
    open_period = get_open_snapshot()
    return render_template(
        'snapshots.html',
        snapshots=snapshots,
        open_period=open_period,
    )


# ── Opening ────────────────────────────────────────────────────────────────────

@snapshots_bp.route('/opening', methods=['POST'])
def take_opening():
    result, doc_id = take_opening_snapshot()
    if result == 'ok':
        flash('New audit period opened successfully.', 'success')
    elif result == 'already_open':
        flash('An audit period is already open. Close it before starting a new one.', 'error')
    else:
        flash('Could not open a new audit period.', 'error')
    return redirect(url_for('snapshots.snapshots_list'))


# ── Closing form ───────────────────────────────────────────────────────────────

@snapshots_bp.route('/closing/<doc_id>', methods=['GET'])
def closing_form(doc_id):
    snapshot = get_snapshot_by_id(doc_id)
    if not snapshot or not snapshot.get('opening'):
        flash('Opening snapshot must be taken before closing.', 'error')
        return redirect(url_for('snapshots.snapshots_list'))
    if snapshot.get('status') == 'closed':
        flash('This period is already closed.', 'error')
        return redirect(url_for('snapshots.snapshots_list'))

    return render_template('snapshots_closing.html', snapshot=snapshot, doc_id=doc_id)


# ── Closing submit ─────────────────────────────────────────────────────────────

@snapshots_bp.route('/closing/<doc_id>', methods=['POST'])
def take_closing(doc_id):
    snapshot = get_snapshot_by_id(doc_id)
    if not snapshot:
        flash('Snapshot not found.', 'error')
        return redirect(url_for('snapshots.snapshots_list'))

    opening_materials = snapshot.get('opening', {}).get('materials', [])
    closing_counts = {}
    for m in opening_materials:
        name = m['name']
        raw = request.form.get(f'closing_{name}', '').strip()
        try:
            closing_counts[name] = float(raw)
        except (ValueError, TypeError):
            closing_counts[name] = 0.0

    result = take_closing_snapshot(doc_id, closing_counts)

    if result == 'ok':
        flash('Audit period closed. Raw material quantities have been updated.', 'success')
    elif result == 'already_closed':
        flash('This period is already closed.', 'error')
    elif result == 'no_opening':
        flash('No opening snapshot found for this period.', 'error')
    else:
        flash('Could not close this period. Please try again.', 'error')

    return redirect(url_for('snapshots.snapshots_list'))
