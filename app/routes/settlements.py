from flask import Blueprint, render_template, request, redirect, url_for, flash
from app.services.settlement_service import get_unsettled_orders, create_payment_settlement
from app.services.order_service import PLATFORMS

settlements_bp = Blueprint('settlements', __name__, url_prefix='/settlements')

@settlements_bp.route('/')
def settlements_list():
    platform_filter = request.args.get('platform', '')
    unsettled_orders = get_unsettled_orders(platform=platform_filter if platform_filter else None)
    
    total_expected = sum(o.get('bank_settlement', 0) for o in unsettled_orders)
    
    return render_template('settlements.html',
                           orders=unsettled_orders,
                           platforms=PLATFORMS,
                           filter_platform=platform_filter,
                           total_expected=total_expected)

@settlements_bp.route('/add', methods=['POST'])
def add_settlement():
    platform = request.form.get('platform', '')
    utr_number = request.form.get('utr_number', '').strip()
    amount_received = request.form.get('amount_received', 0)
    settlement_date = request.form.get('settlement_date', '')
    notes = request.form.get('notes', '').strip()
    
    order_ids = request.form.getlist('order_ids')
    
    if not order_ids:
        flash("No orders selected for settlement.", "error")
        return redirect(url_for('settlements.settlements_list'))
        
    if not utr_number:
        flash("UTR Number is required.", "error")
        return redirect(url_for('settlements.settlements_list'))
        
    create_payment_settlement(
        platform=platform,
        utr_number=utr_number,
        amount_received=amount_received,
        order_ids=order_ids,
        settlement_date=settlement_date,
        notes=notes
    )
    
    flash(f"Settlement logged successfully for {len(order_ids)} orders.", "success")
    return redirect(url_for('settlements.settlements_list'))
