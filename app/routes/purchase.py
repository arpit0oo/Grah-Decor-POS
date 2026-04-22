from flask import Blueprint, render_template, request, redirect, url_for, flash
from datetime import datetime
from app.services.purchase_service import (
    get_all_purchase_orders,
    add_purchase_order,
    mark_po_sent,
    mark_po_received,
    mark_po_paid,
    cancel_po,
    return_po
)
from app.services.inventory_service import get_all_raw_materials

purchase_bp = Blueprint('purchase', __name__, url_prefix='/purchases')

@purchase_bp.route('/')
def purchase_list():
    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')
    
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

    purchases = get_all_purchase_orders(date_from=df, date_to=dt)
    total_spent = sum(p.get('total_cost', 0) for p in purchases if p.get('status') != 'Cancelled')
    raw_materials = get_all_raw_materials()
    
    return render_template('purchase.html', purchases=purchases, total_spent=total_spent,
                           raw_materials=raw_materials, date_from=date_from or '', date_to=date_to or '')

@purchase_bp.route('/add', methods=['POST'])
def purchase_add():
    vendor_name = request.form.get('vendor_name', '').strip()
    
    items = []
    item_names = request.form.getlist('item[]')
    quantities = request.form.getlist('quantity[]')
    unit_costs = request.form.getlist('unit_cost[]')
    
    for i in range(len(item_names)):
        name = item_names[i].strip()
        if not name:
            continue
        qty = quantities[i] if i < len(quantities) else 0
        cost = unit_costs[i] if i < len(unit_costs) else 0
        items.append({
            'item': name,
            'quantity': float(qty),
            'unit_cost': float(cost)
        })
    
    if not vendor_name or not items:
        flash('Invalid purchase details. At least one valid item is required.', 'error')
        return redirect(url_for('purchase.purchase_list'))
        
    add_purchase_order(vendor_name, items)
    flash('Draft Purchase Order created.', 'success')
    return redirect(url_for('purchase.purchase_list'))

@purchase_bp.route('/sent/<po_id>', methods=['POST'])
def purchase_sent(po_id):
    mark_po_sent(po_id)
    flash('Purchase Order marked as Sent.', 'success')
    return redirect(url_for('purchase.purchase_list'))

@purchase_bp.route('/received/<po_id>', methods=['POST'])
def purchase_received(po_id):
    if mark_po_received(po_id):
        flash('Items Received and added to inventory.', 'success')
    else:
        flash('Could not receive items (maybe already received).', 'error')
    return redirect(url_for('purchase.purchase_list'))

@purchase_bp.route('/paid/<po_id>', methods=['POST'])
def purchase_paid(po_id):
    payment_id = request.form.get('payment_id', '').strip()
    if not payment_id:
        flash('Payment ID or UTR is required to mark as paid.', 'error')
        return redirect(url_for('purchase.purchase_list'))
        
    if mark_po_paid(po_id, payment_id):
        flash('Payment logged to cashbook. PO marked as Paid.', 'success')
    else:
        flash('Could not mark as paid.', 'error')
    return redirect(url_for('purchase.purchase_list'))

@purchase_bp.route('/cancel/<po_id>', methods=['POST'])
def purchase_cancel(po_id):
    if cancel_po(po_id):
        flash('Purchase Order cancelled.', 'success')
    else:
        flash('Failed to cancel PO.', 'error')
    return redirect(url_for('purchase.purchase_list'))

@purchase_bp.route('/return/<po_id>', methods=['POST'])
def purchase_return(po_id):
    refund_amount = request.form.get('refund_amount', 0)
    if return_po(po_id, refund_amount=refund_amount):
        flash('Purchase Order returned successfully.', 'success')
    else:
        flash('Failed to return PO.', 'error')
    return redirect(url_for('purchase.purchase_list'))


