from flask import Blueprint, render_template, request, redirect, url_for, flash
from datetime import datetime
from app.services.order_service import (
    get_all_orders, add_order, update_order, delete_order,
    PLATFORMS, STATUSES, REVIEWS
)
from app.services.inventory_service import get_all_ready_stock

orders_bp = Blueprint('orders', __name__, url_prefix='/orders')


@orders_bp.route('/')
def orders_list():
    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')
    platform = request.args.get('platform', '')
    status = request.args.get('status', '')

    df = None
    dt = None
    if date_from:
        try:
            df = datetime.strptime(date_from, '%Y-%m-%d').date()
        except ValueError:
            pass
    if date_to:
        try:
            dt = datetime.strptime(date_to, '%Y-%m-%d').date()
        except ValueError:
            pass

    orders = get_all_orders(date_from=df, date_to=dt,
                            platform=platform or None,
                            status=status or None)

    total_sales = sum(o.get('selling_price', 0) for o in orders)
    total_settlement = sum(o.get('bank_settlement', 0) for o in orders)

    ready_stock = get_all_ready_stock()
    products = sorted(list(set(s['name'] for s in ready_stock if s.get('name'))))
    colors = sorted(list(set(s['color'] for s in ready_stock if s.get('color'))))

    return render_template('orders.html',
                           orders=orders,
                           platforms=PLATFORMS,
                           statuses=STATUSES,
                           reviews=REVIEWS,
                           products=products,
                           colors=colors,
                           total_sales=total_sales,
                           total_settlement=total_settlement,
                           filter_date_from=date_from or '',
                           filter_date_to=date_to or '',
                           filter_platform=platform,
                           filter_status=status)


@orders_bp.route('/add', methods=['POST'])
def order_add():
    data = {
        'date': request.form.get('date', ''),
        'order_id': request.form.get('order_id', '').strip(),
        'customer': request.form.get('customer', '').strip(),
        'number': request.form.get('number', '').strip(),
        'product': request.form.get('product', '').strip(),
        'color': request.form.get('color', '').strip(),
        'platform': request.form.get('platform', ''),
        'selling_price': request.form.get('selling_price', 0),
        'shipping': request.form.get('shipping', 0),
        'refund': request.form.get('refund', 0),
        'tax': request.form.get('tax', 0),
        'marketplace_fee': request.form.get('marketplace_fee', 0),
        'status': request.form.get('status', 'Pending'),
        'reviews': request.form.get('reviews', '').strip(),
    }

    if data['customer'] and data['product']:
        add_order(data)
        flash('Order logged successfully.', 'success')
    else:
        flash('Customer and Product are required.', 'error')

    return redirect(url_for('orders.orders_list'))


@orders_bp.route('/edit/<doc_id>', methods=['POST'])
def order_edit(doc_id):
    data = {
        'date': request.form.get('date', ''),
        'order_id': request.form.get('order_id', '').strip(),
        'customer': request.form.get('customer', '').strip(),
        'number': request.form.get('number', '').strip(),
        'product': request.form.get('product', '').strip(),
        'color': request.form.get('color', '').strip(),
        'platform': request.form.get('platform', ''),
        'selling_price': request.form.get('selling_price', 0),
        'shipping': request.form.get('shipping', 0),
        'refund': request.form.get('refund', 0),
        'tax': request.form.get('tax', 0),
        'marketplace_fee': request.form.get('marketplace_fee', 0),
        'status': request.form.get('status', 'Pending'),
        'reviews': request.form.get('reviews', '').strip(),
    }
    update_order(doc_id, data)
    flash('Order updated.', 'success')
    return redirect(url_for('orders.orders_list'))


@orders_bp.route('/delete/<doc_id>', methods=['POST'])
def orders_delete(doc_id):
    if delete_order(doc_id):
        flash('Order and related records deleted.', 'success')
    else:
        flash('Order not found.', 'error')
    return redirect(url_for('orders.orders_list'))

@orders_bp.route('/bulk_action', methods=['POST'])
def orders_bulk_action():
    action = request.form.get('action')
    order_ids = request.form.getlist('order_ids')
    
    if not order_ids or not action:
        flash('No orders selected or action specified.', 'error')
        return redirect(url_for('orders.orders_list'))
        
    success_count = 0
    if action == 'delete':
        for doc_id in order_ids:
            if delete_order(doc_id):
                success_count += 1
        flash(f'Successfully deleted {success_count} orders.', 'success')
    elif action.startswith('status_'):
        new_status = action.replace('status_', '')
        for doc_id in order_ids:
            # Reusing robust update_order which correctly handles stock recalculations
            update_order(doc_id, {'status': new_status})
            success_count += 1
        flash(f'Successfully changed status of {success_count} orders to {new_status}.', 'success')
    else:
        flash('Invalid action requested.', 'error')
        
    return redirect(url_for('orders.orders_list'))
