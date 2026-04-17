from flask import Blueprint, render_template, request, redirect, url_for, flash
from app.services.audit_service import get_all_audits, get_audit_by_id, finalize_audit
from app.services.inventory_service import get_all_raw_materials

audit_bp = Blueprint('audit', __name__, url_prefix='/audit')


@audit_bp.route('/')
def audit_list():
    """Audit History dashboard."""
    audits = get_all_audits()
    return render_template('audit.html', view='list', audits=audits)


@audit_bp.route('/new')
def audit_new():
    """New Audit — show current system quantities as checkpoint."""
    raw_materials = get_all_raw_materials()
    # Normalise fields
    for m in raw_materials:
        m.setdefault('quantity', 0)
        m.setdefault('price', 0)
        m.setdefault('unit', 'pcs')
    return render_template('audit.html', view='new', raw_materials=raw_materials)


@audit_bp.route('/finalize', methods=['POST'])
def audit_finalize():
    """Process and save a completed audit."""
    doc_ids        = request.form.getlist('doc_id[]')
    names          = request.form.getlist('name[]')
    units          = request.form.getlist('unit[]')
    prices         = request.form.getlist('price[]')
    opening_stocks = request.form.getlist('opening_stock[]')
    purchased_qtys = request.form.getlist('purchased[]')
    notes          = request.form.get('notes', '').strip()

    if not doc_ids:
        flash('No items to audit.', 'error')
        return redirect(url_for('audit.audit_new'))

    items_data = []
    for i, doc_id in enumerate(doc_ids):
        try:
            purchased_val = float(purchased_qtys[i])
        except (ValueError, IndexError):
            purchased_val = 0.0
        items_data.append({
            'doc_id':        doc_id,
            'name':          names[i] if i < len(names) else '',
            'unit':          units[i] if i < len(units) else 'pcs',
            'price':         float(prices[i]) if i < len(prices) else 0,
            'opening_stock': float(opening_stocks[i]) if i < len(opening_stocks) else 0,
            'purchased':     purchased_val,
        })

    finalize_audit(items_data, notes=notes)
    flash('Stock audit saved. Live quantities updated.', 'success')
    return redirect(url_for('audit.audit_list'))


@audit_bp.route('/report/<audit_id>')
def audit_report(audit_id):
    """View a single historical audit report."""
    audit = get_audit_by_id(audit_id)
    if not audit:
        flash('Audit not found.', 'error')
        return redirect(url_for('audit.audit_list'))

    # Rename 'items' → 'line_items' to avoid Jinja2/Python dict.items() method collision
    audit['line_items'] = audit.pop('items', [])

    return render_template('audit.html', view='report', audit=audit)
