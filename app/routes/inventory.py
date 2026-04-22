from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from app.services.inventory_service import (
    get_all_raw_materials, add_raw_material, update_raw_material, delete_raw_material,
    get_all_ready_stock, add_ready_stock, update_ready_stock, delete_ready_stock,
    produce_item, get_inventory_logs, get_product_inventory_logs
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
    today_produced = 0
    today_shipped = 0
    
    for log in logs:
        # Some datetime objects might have timezone attached, safe way:
        dt = log.get('date')
        if dt and hasattr(dt, 'date') and dt.date() == today:
            delta = log.get('delta', 0)
            reason = log.get('reason', '')
            
            if delta > 0:
                today_in += delta
                if 'Produce' in reason or 'Production' in reason:
                    today_produced += delta
            elif delta < 0:
                today_out += abs(delta)
                if 'Shipped' in reason or 'Delivered' in reason:
                    today_shipped += abs(delta)

    tab = request.args.get('tab', 'ready')
    return render_template('inventory.html', 
                           raw_materials=raw, ready_stock=ready, logs=logs, active_tab=tab,
                           today_in=today_in, today_out=today_out, 
                           today_produced=today_produced, today_shipped=today_shipped)


# ── Raw Materials ──────────────────────────────────────────────

@inventory_bp.route('/raw/add', methods=['POST'])
def raw_add():
    name = request.form.get('name', '').strip()
    quantity = request.form.get('quantity', 0)
    unit = request.form.get('unit', 'pcs').strip()
    price = request.form.get('price', 0)
    if name:
        add_raw_material(name, quantity, unit, price)
        flash('Raw material added.', 'success')
    else:
        flash('Name is required.', 'error')
    return redirect(url_for('inventory.inventory_list', tab='raw'))


@inventory_bp.route('/raw/edit/<doc_id>', methods=['POST'])
def raw_edit(doc_id):
    data = {}
    if request.form.get('name'):
        data['name'] = request.form['name'].strip()
    if request.form.get('quantity') is not None:
        data['quantity'] = float(request.form['quantity'])
    if request.form.get('unit'):
        data['unit'] = request.form['unit'].strip()
    if request.form.get('price') is not None:
        data['price'] = float(request.form['price'])
    if data:
        update_raw_material(doc_id, data)
        flash('Raw material updated.', 'success')
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
    if name:
        add_ready_stock(name, color, quantity, cost_price)
        flash('Ready stock item added.', 'success')
    else:
        flash('Product name is required.', 'error')
    return redirect(url_for('inventory.inventory_list', tab='ready'))


@inventory_bp.route('/ready/edit/<doc_id>', methods=['POST'])
def ready_edit(doc_id):
    data = {}
    if request.form.get('name'):
        data['name'] = request.form['name'].strip()
    if request.form.get('color') is not None:
        data['color'] = request.form['color'].strip()
    if request.form.get('quantity') is not None:
        data['quantity'] = float(request.form['quantity'])
    if request.form.get('cost_price') is not None:
        data['cost_price'] = float(request.form['cost_price'])
    if data:
        update_ready_stock(doc_id, data)
        flash('Ready stock updated.', 'success')
    return redirect(url_for('inventory.inventory_list', tab='ready'))


@inventory_bp.route('/ready/delete/<doc_id>', methods=['POST'])
def ready_delete(doc_id):
    delete_ready_stock(doc_id)
    flash('Ready stock item deleted.', 'success')
    return redirect(url_for('inventory.inventory_list', tab='ready'))


# ── Produce ────────────────────────────────────────────────────

@inventory_bp.route('/produce', methods=['POST'])
def produce():
    product_name = request.form.get('product_name', '').strip()
    product_color = request.form.get('product_color', '').strip()
    produce_qty = request.form.get('produce_qty', 1)

    # Collect raw materials used (dynamic form fields)
    raw_items = []
    i = 0
    while True:
        mat_name = request.form.get(f'raw_name_{i}')
        mat_qty = request.form.get(f'raw_qty_{i}')
        if mat_name is None:
            break
        if mat_name.strip() and mat_qty:
            raw_items.append({'name': mat_name.strip(), 'quantity_used': float(mat_qty)})
        i += 1

    if product_name and raw_items:
        produce_item(raw_items, product_name, product_color, produce_qty)
        flash(f'Produced {produce_qty} x {product_name}.', 'success')
    else:
        flash('Please fill in product and raw materials.', 'error')

    return redirect(url_for('inventory.inventory_list', tab='ready'))


# ── API endpoints for JS ───────────────────────────────────────

@inventory_bp.route('/api/raw', methods=['GET'])
def api_raw_list():
    return jsonify(get_all_raw_materials())


@inventory_bp.route('/api/ready', methods=['GET'])
def api_ready_list():
    return jsonify(get_all_ready_stock())


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
