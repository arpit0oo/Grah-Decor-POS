from flask import Blueprint, render_template, request, redirect, url_for, flash
from datetime import datetime
from app.services.purchase_service import get_all_purchases, add_purchase, delete_purchase

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

    purchases = get_all_purchases(date_from=df, date_to=dt)
    total_spent = sum(p.get('total_cost', 0) for p in purchases)

    return render_template('purchase.html',
                           purchases=purchases,
                           total_spent=total_spent,
                           date_from=date_from or '',
                           date_to=date_to or '')


@purchase_bp.route('/add', methods=['POST'])
def purchase_add():
    vendor_name = request.form.get('vendor_name', '').strip()
    item = request.form.get('item', '').strip()
    quantity = request.form.get('quantity', 0)
    unit_cost = request.form.get('unit_cost', 0)
    notes = request.form.get('notes', '').strip()

    if vendor_name and item and float(quantity) > 0 and float(unit_cost) > 0:
        add_purchase(vendor_name, item, quantity, unit_cost, notes)
        flash('Purchase logged successfully.', 'success')
    else:
        flash('Please fill all required fields.', 'error')

    return redirect(url_for('purchase.purchase_list'))


@purchase_bp.route('/delete/<doc_id>', methods=['POST'])
def purchase_delete(doc_id):
    if delete_purchase(doc_id):
        flash('Purchase deleted and inventory/cashbook reversed.', 'success')
    else:
        flash('Purchase not found.', 'error')
    return redirect(url_for('purchase.purchase_list'))
