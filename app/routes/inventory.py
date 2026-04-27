from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from app.services.inventory_service import (
    get_all_raw_materials, add_raw_material, update_raw_material, delete_raw_material,
    get_all_ready_stock, get_ready_stock_grouped, add_ready_stock, add_ready_stock_variant,
    update_ready_stock, delete_ready_stock, adjust_ready_stock_qty,
    get_inventory_logs, get_product_inventory_logs
)

inventory_bp = Blueprint('inventory', __name__, url_prefix='/inventory')


from datetime import datetime, timezone

@inventory_bp.route('/')
def inventory_list():
    raw = get_all_raw_materials()
    ready = get_all_ready_stock()
    logs = get_inventory_logs(limit=200)
    
    # Calculate Quick Analytics
    today = datetime.now(timezone.utc).date()
    today_in = 0
    today_out = 0
    today_log_count = 0
    today_shipped = 0
    
    for log in logs:
        # Some datetime objects might have timezone attached, safe way:
        dt = log.get('date')
        if dt and hasattr(dt, 'date') and dt.date() == today:
            today_log_count += 1
            delta = log.get('delta', 0)
            reason = log.get('reason', '')
            
            if delta > 0:
                today_in += delta
            elif delta < 0:
                today_out += abs(delta)
                if 'Shipped' in reason or 'Delivered' in reason:
                    today_shipped += abs(delta)

    tab = request.args.get('tab', 'ready')
    return render_template('inventory.html', 
                           raw_materials=raw, ready_stock=get_ready_stock_grouped(), logs=logs, active_tab=tab,
                           today_in=today_in, today_out=today_out, 
                           today_log_count=today_log_count, today_shipped=today_shipped)


# ── Raw Materials ──────────────────────────────────────────────

@inventory_bp.route('/raw/add', methods=['POST'])
def raw_add():
    name = request.form.get('name', '').strip()
    quantity = request.form.get('quantity', 0)
    unit = request.form.get('unit', 'pcs').strip()
    if name:
        add_raw_material(name, quantity, unit)
        flash('Raw material added.', 'success')
    else:
        flash('Name is required.', 'error')
    return redirect(url_for('inventory.inventory_list', tab='raw'))


@inventory_bp.route('/raw/edit/<doc_id>', methods=['POST'])
def raw_edit(doc_id):
    data = {}
    # Name and Price are LOCKED — only unit can change
    if request.form.get('unit'):
        data['unit'] = request.form['unit'].strip()
    if data:
        update_raw_material(doc_id, data)
        flash('Raw material unit updated.', 'success')
    return redirect(url_for('inventory.inventory_list', tab='raw'))


@inventory_bp.route('/raw/delete/<doc_id>', methods=['POST'])
def raw_delete(doc_id):
    delete_raw_material(doc_id)
    flash('Raw material deleted.', 'success')
    return redirect(url_for('inventory.inventory_list', tab='raw'))


# ── Ready Stock ────────────────────────────────────────────────

@inventory_bp.route('/ready/add', methods=['POST'])
def ready_add():
    name = request.form.get('name', '').strip()
    color = request.form.get('color', '').strip()
    quantity = request.form.get('quantity', 0)
    cost_price = request.form.get('cost_price', 0)
    reason = request.form.get('reason', 'Manual Add').strip() or 'Manual Add'
    if name:
        add_ready_stock(name, color, quantity, cost_price, reason=reason)
        flash('Ready stock item added.', 'success')
    else:
        flash('Product name is required.', 'error')
    return redirect(url_for('inventory.inventory_list', tab='ready'))


@inventory_bp.route('/ready/edit/<doc_id>', methods=['POST'])
def ready_edit(doc_id):
    data = {}
    # Name and Quantity are LOCKED — use Adjust Stock to change quantity
    if request.form.get('cost_price') is not None:
        data['cost_price'] = float(request.form.get('cost_price') or 0)
    if data:
        try:
            update_ready_stock(doc_id, data)
            flash('Cost price updated.', 'success')
        except ValueError as e:
            flash(str(e), 'error')
    return redirect(url_for('inventory.inventory_list', tab='ready'))


@inventory_bp.route('/ready/adjust/<doc_id>', methods=['POST'])
def ready_adjust(doc_id):
    adjustment = request.form.get('adjustment', '').strip()
    reason = request.form.get('reason', '').strip()
    notes = request.form.get('notes', '').strip()

    if not adjustment or not reason:
        flash('Adjustment quantity and reason are required.', 'error')
        return redirect(url_for('inventory.inventory_list', tab='ready'))

    try:
        delta = int(float(adjustment))
    except ValueError:
        flash('Invalid adjustment quantity.', 'error')
        return redirect(url_for('inventory.inventory_list', tab='ready'))

    if delta < 1:
        flash('Only positive additions are allowed. Stock is reduced through orders.', 'error')
        return redirect(url_for('inventory.inventory_list', tab='ready'))

    from app.services.inventory_service import get_all_ready_stock
    all_docs = get_all_ready_stock()
    item = next((d for d in all_docs if d['id'] == doc_id), None)
    if not item:
        flash('Item not found.', 'error')
        return redirect(url_for('inventory.inventory_list', tab='ready'))

    full_reason = f"{reason}: {notes}" if notes else reason
    adjust_ready_stock_qty(
        item.get('name', ''),
        item.get('color', ''),
        delta,
        0,
        reason=full_reason,
        ref_id=doc_id
    )
    direction = f"+{delta}" if delta > 0 else str(delta)
    flash(f'Stock adjusted by {direction} for {item.get("name")}. Reason: {reason}.', 'success')
    return redirect(url_for('inventory.inventory_list', tab='ready'))


@inventory_bp.route('/ready/delete/<doc_id>', methods=['POST'])
def ready_delete(doc_id):
    # Deletions disabled — inventory records are permanent
    flash('Inventory records cannot be deleted. Set quantity to 0 to zero it out.', 'error')
    return redirect(url_for('inventory.inventory_list', tab='ready'))


@inventory_bp.route('/ready/add_variant/<parent_id>', methods=['POST'])
def ready_add_variant(parent_id):
    from app.services.inventory_service import get_all_ready_stock
    db_docs = get_all_ready_stock()
    parent = next((d for d in db_docs if d['id'] == parent_id), None)
    if not parent:
        flash('Parent product not found.', 'error')
        return redirect(url_for('inventory.inventory_list', tab='ready'))
    
    variant_name = request.form.get('variant_name', '').strip()
    quantity = request.form.get('quantity', 0)
    
    if not variant_name:
        flash('Variant name is required.', 'error')
        return redirect(url_for('inventory.inventory_list', tab='ready'))
    
    add_ready_stock_variant(parent_id, parent['name'], variant_name, quantity)
    flash(f'Variant "{variant_name}" added to {parent["name"]}.', 'success')
    return redirect(url_for('inventory.inventory_list', tab='ready'))





# ── API endpoints for JS ───────────────────────────────────────

@inventory_bp.route('/api/raw', methods=['GET'])
def api_raw_list():
    return jsonify(get_all_raw_materials())


@inventory_bp.route('/api/ready', methods=['GET'])
def api_ready_list():
    return jsonify(get_all_ready_stock())


@inventory_bp.route('/api/variants', methods=['GET'])
def api_variants():
    """Return variants (children) for a given parent product name."""
    name = request.args.get('name', '')
    if not name:
        return jsonify([])
    all_docs = get_all_ready_stock()
    # Find parent doc
    parent = next((d for d in all_docs if d.get('name') == name and not d.get('parent_id')), None)
    if not parent:
        return jsonify([])
    # Find children
    children = [d for d in all_docs if d.get('parent_id') == parent['id']]
    return jsonify([{'id': c['id'], 'color': c.get('color', ''), 'quantity': c.get('quantity', 0)} for c in children])


@inventory_bp.route('/api/product-logs', methods=['GET'])
def api_product_logs():
    name = request.args.get('name')
    color = request.args.get('color')
    if not name:
        return jsonify({'error': 'Name is required'}), 400
    
    logs = get_product_inventory_logs(name, color)
    # Serialize datetime for JSON
    for log in logs:
        if log.get('date'):
            log['date'] = log['date'].isoformat()
    return jsonify(logs)


@inventory_bp.route('/api/raw-purchase-history', methods=['GET'])
def api_raw_purchase_history():
    """Return all purchase orders containing a given raw material name.
    Handles both legacy single-item POs (po.item) and multi-item POs (po.items[]).
    """
    name = request.args.get('name', '').strip()
    if not name:
        return jsonify({'error': 'Name is required'}), 400

    from app.services.purchase_service import get_all_purchase_orders
    all_pos = get_all_purchase_orders()

    result = []
    for po in all_pos:
        matched_qty  = 0
        matched_cost = 0.0

        # ── Multi-item POs: check the items[] array ────────────────────────
        items = po.get('items', [])
        if items:
            for it in items:
                if (it.get('item') or '').strip().lower() == name.lower():
                    qty       = float(it.get('quantity', 0))
                    unit_cost = float(it.get('unit_cost') or it.get('price', 0))
                    matched_qty  += qty
                    matched_cost += qty * unit_cost
        else:
            # ── Legacy single-item PO: check top-level item field ──────────
            if (po.get('item') or '').strip().lower() == name.lower():
                matched_qty  = float(po.get('quantity', 0))
                unit_cost    = float(po.get('unit_cost', 0))
                matched_cost = float(po.get('total_cost') or matched_qty * unit_cost)

        if matched_qty == 0:
            continue  # this PO doesn't involve the requested material

        created  = po.get('created_at')
        date_str = created.strftime('%d/%m/%Y') if created and hasattr(created, 'strftime') else '-'

        result.append({
            'po_number':   po.get('po_number', '-'),
            'date':        date_str,
            'vendor_name': po.get('vendor_name', '-'),
            'quantity':    matched_qty,
            'unit_cost':   matched_cost / matched_qty if matched_qty else 0,
            'total_cost':  matched_cost,
            'status':      po.get('status', '-'),
        })

    return jsonify(result)
