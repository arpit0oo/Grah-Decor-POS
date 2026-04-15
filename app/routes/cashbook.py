from flask import Blueprint, render_template, request, flash, redirect, url_for
from datetime import datetime
from app.services.cashbook_service import get_today_transactions, get_all_transactions, get_running_balance, add_cashbook_entry

cashbook_bp = Blueprint('cashbook', __name__, url_prefix='/cashbook')


@cashbook_bp.route('/')
def dashboard():
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

    if df or dt:
        transactions = get_all_transactions(date_from=df, date_to=dt)
    else:
        transactions = get_all_transactions()

    today_txns = get_today_transactions()
    balance = get_running_balance()

    today_inflow = sum(t['amount'] for t in today_txns if t['type'] == 'inflow')
    today_outflow = sum(t['amount'] for t in today_txns if t['type'] == 'outflow')
    today_net = today_inflow - today_outflow

    return render_template('cashbook.html',
                           transactions=transactions,
                           balance=balance,
                           today_inflow=today_inflow,
                           today_outflow=today_outflow,
                           today_net=today_net,
                           date_from=date_from or '',
                           date_to=date_to or '')

@cashbook_bp.route('/add_expense', methods=['POST'])
def add_expense():
    amount = request.form.get('amount')
    category = request.form.get('category', 'Misc')
    notes = request.form.get('notes', '').strip()
    expense_date = request.form.get('date', '').strip()

    if not amount:
        flash('Amount is required.', 'error')
        return redirect(url_for('cashbook.dashboard'))

    try:
        amount_val = float(amount)
        if amount_val <= 0:
            raise ValueError
    except ValueError:
        flash('Invalid amount.', 'error')
        return redirect(url_for('cashbook.dashboard'))

    add_cashbook_entry(
        entry_type='outflow',
        category=category,
        description=notes,
        amount=amount_val,
        source='manual_expense',
        entry_date=expense_date
    )

    flash('Manual expense logged successfully.', 'success')
    return redirect(url_for('cashbook.dashboard'))
