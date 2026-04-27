from datetime import datetime, timezone
from app import get_db

def generate_vendor_id():
    db = get_db()
    docs = list(db.collection('vendors').order_by('created_at', direction='DESCENDING').limit(1).stream())
    if not docs:
        return "GDV-0001"
    
    last_doc = docs[0].to_dict()
    last_id = last_doc.get('vendor_id', '')
    if last_id.startswith('GDV-'):
        try:
            num = int(last_id.replace('GDV-', ''))
            return f"GDV-{num + 1:04d}"
        except:
            pass
    count = len(list(db.collection('vendors').stream()))
    return f"GDV-{count + 1:04d}"

def generate_customer_id():
    db = get_db()
    docs = list(db.collection('customers').order_by('created_at', direction='DESCENDING').limit(1).stream())
    if not docs:
        return "GDC-0001"
    
    last_doc = docs[0].to_dict()
    last_id = last_doc.get('customer_id', '')
    if last_id.startswith('GDC-'):
        try:
            num = int(last_id.replace('GDC-', ''))
            return f"GDC-{num + 1:04d}"
        except:
            pass
    count = len(list(db.collection('customers').stream()))
    return f"GDC-{count + 1:04d}"

def get_all_vendors():
    db = get_db()
    docs = db.collection('vendors').order_by('created_at', direction='DESCENDING').stream()
    return [{'id': d.id, **d.to_dict()} for d in docs]

def get_all_customers():
    db = get_db()
    docs = db.collection('customers').order_by('created_at', direction='DESCENDING').stream()
    return [{'id': d.id, **d.to_dict()} for d in docs]

def add_vendor(name, phone_numbers):
    db = get_db()
    vendor_id = generate_vendor_id()
    
    if not phone_numbers:
        phone_numbers = ["Not available"]
        
    doc_ref = db.collection('vendors').document()
    doc_ref.set({
        'vendor_id': vendor_id,
        'name': name,
        'phone_numbers': phone_numbers,
        'created_at': datetime.now(timezone.utc)
    })
    return vendor_id

def add_customer(name, phone_numbers, platform_used=None, recent_order_id=None):
    db = get_db()
    customer_id = generate_customer_id()
    
    if not phone_numbers:
        phone_numbers = ["Not available"]
        
    doc_ref = db.collection('customers').document()
    doc_ref.set({
        'customer_id': customer_id,
        'name': name,
        'phone_numbers': phone_numbers,
        'platform_used': platform_used,
        'recent_order_id': recent_order_id,
        'created_at': datetime.now(timezone.utc)
    })
    return customer_id

def update_customer_metadata(customer_doc_id, platform_used=None, recent_order_id=None):
    db = get_db()
    doc_ref = db.collection('customers').document(customer_doc_id)
    updates = {}
    if platform_used:
        updates['platform_used'] = platform_used
    if recent_order_id:
        updates['recent_order_id'] = recent_order_id
        
    if updates:
        updates['updated_at'] = datetime.now(timezone.utc)
        doc_ref.update(updates)

def update_vendor(vendor_doc_id, name, phone_numbers):
    db = get_db()
    doc_ref = db.collection('vendors').document(vendor_doc_id)
    
    if not phone_numbers:
        phone_numbers = ["Not available"]
        
    doc_ref.update({
        'name': name,
        'phone_numbers': phone_numbers,
        'updated_at': datetime.now(timezone.utc)
    })

def update_customer(customer_doc_id, name, phone_numbers):
    db = get_db()
    doc_ref = db.collection('customers').document(customer_doc_id)

    if not phone_numbers:
        phone_numbers = ["Not available"]

    doc_ref.update({
        'name': name,
        'phone_numbers': phone_numbers,
        'updated_at': datetime.now(timezone.utc)
    })
