import os
import firebase_admin
from firebase_admin import credentials, firestore
from dotenv import load_dotenv

load_dotenv()

def audit_database():
    key_path = os.getenv('FIREBASE_KEY_PATH', 'serviceAccountKey.json')
    if not os.path.isabs(key_path):
        # Assuming script is in root
        key_path = os.path.join(os.getcwd(), key_path)

    if not firebase_admin._apps:
        cred = credentials.Certificate(key_path)
        firebase_admin.initialize_app(cred)

    db = firestore.client()
    
    collections = ['orders', 'ready_stock', 'raw_materials', 'purchases', 'cashbook', 'inventory_log']
    
    print("--- FIRESTORE DATA INTEGRITY AUDIT ---\n")
    
    for coll_name in collections:
        print(f"Checking Collection: {coll_name}")
        docs = list(db.collection(coll_name).limit(3).stream())
        
        if not docs:
            print(f"  [!] Collection is EMPTY or doesn't exist.")
            continue
            
        print(f"  [✓] Found {len(docs)} sample records.")
        for doc in docs:
            data = doc.to_dict()
            print(f"  - Document ID: {doc.id}")
            
            # Check for critical fields
            missing = []
            if coll_name == 'ready_stock':
                for f in ['name', 'color', 'quantity', 'reserved_quantity', 'cost_price']:
                    if f not in data: missing.append(f)
            
            elif coll_name == 'orders':
                for f in ['order_id', 'customer', 'product', 'status', 'bank_settlement', 'created_at']:
                    if f not in data: missing.append(f)
            
            elif coll_name == 'inventory_log':
                for f in ['date', 'item_name', 'delta', 'reason']:
                    if f not in data: missing.append(f)

            if missing:
                print(f"    [!] MISSING FIELDS: {missing}")
            else:
                print(f"    [✓] All core fields present.")
                
        print("-" * 30)

if __name__ == "__main__":
    audit_database()
