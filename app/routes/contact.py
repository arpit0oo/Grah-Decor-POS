from flask import Blueprint, render_template, request, flash, redirect, url_for
from app.services.contact_service import get_all_vendors, get_all_customers, add_vendor

contact_bp = Blueprint('contact', __name__, url_prefix='/contacts')

@contact_bp.route('/')
def contacts_list():
    tab = request.args.get('tab', 'vendors')
    vendors = get_all_vendors()
    customers = get_all_customers()
    return render_template('contacts.html', vendors=vendors, customers=customers, active_tab=tab)

@contact_bp.route('/vendor/add', methods=['POST'])
def add_vendor_route():
    name = request.form.get('name', '').strip()
    
    # Extract multiple phone numbers dynamically
    phone_numbers = []
    for key, value in request.form.items():
        if key.startswith('phone_') and value.strip():
            phone_numbers.append(value.strip())
            
    if not name:
        flash('Vendor name is required.', 'error')
        return redirect(url_for('contact.contacts_list', tab='vendors'))
        
    add_vendor(name, phone_numbers)
    flash('Vendor added successfully.', 'success')
    return redirect(url_for('contact.contacts_list', tab='vendors'))
