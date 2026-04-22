from flask import Blueprint, render_template, request, redirect, url_for, flash
from datetime import datetime
from app.services.purchase_service import (
    get_all_purchase_orders,
    add_purchase_order,
    mark_po_sent,
    mark_po_received,
    mark_po_paid,
    cancel_po,
    revert_cancelled_to_paid
)

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
    
    return render_template('purchase.html', purchases=purchases, total_spent=total_spent)

@purchase_bp.route('/add', methods=['POST'])
def purchase_add():
    vendor_name = request.form.get('vendor_name', '').strip()
    item = request.form.get('item', '').strip()
    quantity = request.form.get('quantity', 0)
    unit_cost = request.form.get('unit_cost', 0)
    
    if not (vendor_name and item and float(quantity) > 0):
        flash('Invalid purchase details.', 'error')
        return redirect(url_for('purchase.purchase_list'))
        
    add_purchase_order(vendor_name, item, quantity, unit_cost)
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

@purchase_bp.route('/revert_to_paid/<po_id>', methods=['POST'])
def purchase_revert_to_paid(po_id):
    payment_id = request.form.get('payment_id', '').strip()
    
    if not payment_id:
        flash('Payment ID or UTR is required to revert and mark as paid.', 'error')
        return redirect(url_for('purchase.purchase_list'))
        
    if revert_cancelled_to_paid(po_id, payment_id):
        flash('Purchase Order forcefully reverted to Paid. Inventory and cash amounts logged.', 'success')
    else:
        flash('Could not revert PO.', 'error')
    return redirect(url_for('purchase.purchase_list'))
