from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from app import get_db
from app.services.inventory_service import (
    get_all_raw_materials, add_raw_material, update_raw_material, delete_raw_material,
    get_all_ready_stock, get_ready_stock_grouped, add_ready_stock, add_ready_stock_variant,
    update_ready_stock, delete_ready_stock, adjust_ready_stock_qty,
    get_inventory_logs, get_product_inventory_logs
)

inventory_bp = Blueprint('inventory', __name__, url_prefix='/inventory')


from datetime import datetime, timezone, date as date_type
from google.cloud.firestore_v1 import FieldFilter

@inventory_bp.route('/')
def inventory_list():
    raw = get_all_raw_materials()
    ready = get_all_ready_stock()
    item_name = request.args.get('item_name')
    color = request.args.get('color')
    cursor_id = request.args.get('cursor_id')
    direction = request.args.get('direction', 'next')
    
    logs, has_prev, has_next = get_inventory_logs(
        item_name=item_name or None,
        color=color or None,
        cursor_id=cursor_id,
        direction=direction,
        limit=20
    )
    
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
                           today_log_count=today_log_count, today_shipped=today_shipped,
                           filter_item_name=item_name or '', filter_color=color or '',
                           has_prev_log=has_prev, has_next_log=has_next)


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
    if request.form.get('unit'):
        data['unit'] = request.form['unit'].strip()
    if request.form.get('name'):
        data['name'] = request.form['name'].strip()
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
    name        = request.form.get('name', '').strip()
    color       = request.form.get('color', '').strip()
    quantity    = request.form.get('quantity', 0)
    cost_price  = request.form.get('cost_price', 0)
    min_stock   = request.form.get('min_stock', 0)
    reason      = request.form.get('reason', 'Manual Add').strip() or 'Manual Add'
    has_variants = request.form.get('has_variants') == '1'
    if name:
        add_ready_stock(name, color, quantity, cost_price, reason=reason,
                        min_stock=min_stock, has_variants=has_variants)
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
    if request.form.get('min_stock') is not None:
        data['min_stock'] = int(float(request.form.get('min_stock') or 0))
    if data:
        try:
            update_ready_stock(doc_id, data)
            flash('Product updated.', 'success')
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
    min_stock = request.form.get('min_stock', 0)

    if not variant_name:
        flash('Variant name is required.', 'error')
        return redirect(url_for('inventory.inventory_list', tab='ready'))

    add_ready_stock_variant(parent_id, parent['name'], variant_name, quantity, min_stock=min_stock)
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


@inventory_bp.route('/api/raw-stock-ledger', methods=['GET'])
def api_raw_stock_ledger():
    """
    Return a combined chronological stock ledger for a raw material.

    Inflows: purchase_orders where this material appears and status is Received or Paid.
    Outflows + Adjustments: inventory_log entries for item_name == name (any delta != 0).

    Response is sorted newest-first, with a running_balance column computed
    from oldest to newest so the client can display it in either order.

    Each entry shape:
      { iso_date, date_str, type, reference, delta, running_balance }
    """
    name = request.args.get('name', '').strip()
    if not name:
        return jsonify({'error': 'Name is required'}), 400

    from app import get_db
    from app.services.inventory_service import get_product_inventory_logs

    events = []  # list of {iso_date, date_str, type, reference, delta}

    # ── inventory_log entries (all deltas != 0) ────────────────────────────
    # Single authoritative source — adjust_raw_material_qty() always writes
    # here on every PO receipt, so no separate purchase_orders read is needed.
    logs = get_product_inventory_logs(name, color=None, limit=500)
    for log in logs:
        delta = float(log.get('delta', 0))
        if delta == 0:
            continue  # informational notes — skip from ledger

        dt = log.get('date')
        iso = dt.isoformat() if dt and hasattr(dt, 'isoformat') else ''
        date_str = dt.strftime('%d/%m/%Y') if dt and hasattr(dt, 'strftime') else '-'
        reason = log.get('reason') or '-'
        ref_id = log.get('reference_id') or ''

        # Classify the type from the reason string
        r_lower = reason.lower()
        if 'audit' in r_lower:
            ev_type = 'Audit Adjustment'
        elif 'returned' in r_lower or 'cancelled' in r_lower or 'reversal' in r_lower:
            ev_type = 'PO Return'
        elif 'production' in r_lower or 'consumed' in r_lower or 'manufactured' in r_lower:
            ev_type = 'Production'
        elif 'purchase' in r_lower or 'received' in r_lower:
            ev_type = 'PO Received'
        elif 'manual add' in r_lower or 'manual adjustment' in r_lower:
            ev_type = 'Manual'
        else:
            ev_type = 'Inflow' if delta > 0 else 'Outflow'

        events.append({
            'iso_date':  iso,
            'date_str':  date_str,
            'type':      ev_type,
            'reference': reason,
            'delta':     delta,
        })

    # ── 3. Sort oldest → newest, then reverse for newest-first display ────
    events.sort(key=lambda e: e['iso_date'])
    events.reverse()
    return jsonify(events)


@inventory_bp.route('/api/raw-material-price-history/<material_id>', methods=['GET'])
def api_raw_material_price_history(material_id):
    """
    Return the price_history array from a raw_material document.
    Dates are serialised to ISO-8601 strings for JSON transport.
    """
    db = get_db()
    doc = db.collection('raw_materials').document(material_id).get()
    if not doc.exists:
        return jsonify({'error': 'Material not found'}), 404

    history = doc.to_dict().get('price_history', [])

    # Serialise any datetime objects so JSON encoding never fails
    serialised = []
    for entry in history:
        e = dict(entry)
        if hasattr(e.get('date'), 'isoformat'):
            e['date'] = e['date'].isoformat()
        e['qty_received'] = float(e.get('qty_received', 0))
        serialised.append(e)

    # Sort newest-first
    serialised.sort(key=lambda x: x.get('date', ''), reverse=True)
    return jsonify(serialised)


@inventory_bp.route('/api/raw-materials-wac-summary', methods=['GET'])
def api_raw_materials_wac_summary():
    """
    Returns the total WAC stock value across all raw materials.
    WAC per material = sum(unit_cost × qty_received) / sum(qty_received)
    Total = sum over all materials of WAC × current_quantity.
    Materials with no price_history entries are valued at price × quantity.
    """
    db = get_db()
    docs = db.collection('raw_materials').stream()

    total_wac_value = 0.0
    breakdown = []

    for d in docs:
        m    = d.to_dict()
        name = m.get('name', '')
        qty  = float(m.get('quantity', 0))
        history = m.get('price_history', [])

        if history:
            total_cost_x_qty = sum(
                float(e.get('unit_cost', 0)) * float(e.get('qty_received', 0))
                for e in history
            )
            total_qty_received = sum(float(e.get('qty_received', 0)) for e in history)
            wac = (total_cost_x_qty / total_qty_received) if total_qty_received > 0 else 0.0
        else:
            # Fall back to the stored price field for materials with no PO history
            wac = float(m.get('price', 0))

        material_value = wac * qty
        total_wac_value += material_value
        breakdown.append({
            'name':            name,
            'quantity':        qty,
            'wac':             round(wac, 4),
            'material_value':  round(material_value, 2),
        })

    return jsonify({
        'total_wac_value': round(total_wac_value, 2),
        'breakdown':       breakdown,
    })


@inventory_bp.route('/api/free-gifts', methods=['GET'])
def api_free_gifts():
    """
    Return all free-gift order items across all orders, with optional
    date filtering (date_from / date_to query params, YYYY-MM-DD).
    Defaults to the current calendar month when no filters are supplied.

    Each item in the response:
      date, order_id, customer_id, customer_name,
      product_name, variant, qty, unit_cost, total_cost_absorbed

    Also returns summary totals:
      total_gift_items, total_qty_gifted, total_cost_absorbed
    """
    db = get_db()
    now = datetime.now(timezone.utc)

    # ── Date range parsing (default = current month) ───────────────────────
    date_from_str = request.args.get('date_from', '')
    date_to_str   = request.args.get('date_to', '')

    if date_from_str:
        try:
            date_from_dt = datetime.strptime(date_from_str, '%Y-%m-%d').replace(tzinfo=timezone.utc)
        except ValueError:
            date_from_dt = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    else:
        date_from_dt = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    if date_to_str:
        try:
            import calendar
            dt = datetime.strptime(date_to_str, '%Y-%m-%d')
            # end of day
            date_to_dt = dt.replace(hour=23, minute=59, second=59, microsecond=999999, tzinfo=timezone.utc)
        except ValueError:
            import calendar
            last_day = calendar.monthrange(now.year, now.month)[1]
            date_to_dt = now.replace(day=last_day, hour=23, minute=59, second=59, microsecond=999999)
    else:
        import calendar
        last_day = calendar.monthrange(now.year, now.month)[1]
        date_to_dt = now.replace(day=last_day, hour=23, minute=59, second=59, microsecond=999999)

    # ── Fetch orders within the date range ────────────────────────────────
    orders_query = (
        db.collection('orders')
          .where(filter=FieldFilter('date', '>=', date_from_dt))
          .where(filter=FieldFilter('date', '<=', date_to_dt))
          .stream()
    )

    # ── Collect gift items + unique customer_ids for name lookup ──────────
    gift_rows = []
    customer_ids_needed = set()

    for order_doc in orders_query:
        order = order_doc.to_dict()
        order_date = order.get('date')
        order_id   = order.get('order_id', '')
        cust_id    = order.get('customer_id', '')

        for item in order.get('order_items', []):
            if not item.get('is_free_gift', False):
                continue

            qty       = float(item.get('quantity', 1))
            unit_cost = float(item.get('unit_cost', 0) or 0)
            gift_rows.append({
                '_order_date': order_date,
                'date':        order_date.strftime('%d/%m/%Y') if order_date and hasattr(order_date, 'strftime') else '',
                'date_iso':    order_date.isoformat() if order_date and hasattr(order_date, 'isoformat') else '',
                'order_id':    order_id,
                'customer_id': cust_id,
                'customer_name': order.get('customer', ''),  # pre-filled, may be overwritten by lookup
                'product_name': item.get('product', ''),
                'variant':      item.get('color', '') or '\u2014',
                'qty':          qty,
                'unit_cost':    unit_cost,
                'total_cost_absorbed': round(qty * unit_cost, 2),
            })
            if cust_id:
                customer_ids_needed.add(cust_id)

    # ── Bulk customer name lookup ──────────────────────────────────────────
    # Firestore 'in' queries are limited to 30 values; chunk as needed.
    if customer_ids_needed:
        id_list = list(customer_ids_needed)
        cust_map = {}  # customer_id -> display name
        chunk_size = 30
        for i in range(0, len(id_list), chunk_size):
            chunk = id_list[i:i + chunk_size]
            cust_docs = (
                db.collection('customers')
                  .where(filter=FieldFilter('customer_id', 'in', chunk))
                  .stream()
            )
            for cdoc in cust_docs:
                cd = cdoc.to_dict()
                cust_map[cd.get('customer_id', '')] = cd.get('name', '')

        for row in gift_rows:
            cid = row['customer_id']
            if cid and cid in cust_map:
                row['customer_name'] = cust_map[cid]

    # ── Sort newest-first ──────────────────────────────────────────────────
    gift_rows.sort(key=lambda r: r.get('date_iso', ''), reverse=True)

    # Strip internal sort key before returning
    for row in gift_rows:
        row.pop('_order_date', None)

    # ── Summary totals ────────────────────────────────────────────────────
    total_gift_items    = len(gift_rows)
    total_qty_gifted    = sum(r['qty'] for r in gift_rows)
    total_cost_absorbed = round(sum(r['total_cost_absorbed'] for r in gift_rows), 2)

    return jsonify({
        'items':               gift_rows,
        'total_gift_items':    total_gift_items,
        'total_qty_gifted':    total_qty_gifted,
        'total_cost_absorbed': total_cost_absorbed,
        'date_from':           date_from_str or date_from_dt.strftime('%Y-%m-%d'),
        'date_to':             date_to_str   or date_to_dt.strftime('%Y-%m-%d'),
    })
