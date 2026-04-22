import os
import firebase_admin
from firebase_admin import credentials, firestore
from dotenv import load_dotenv

load_dotenv()

def migrate_reserved_quantity():
    key_path = os.getenv('FIREBASE_KEY_PATH', 'serviceAccountKey.json')
    if not os.path.isabs(key_path):
        key_path = os.path.join(os.getcwd(), key_path)

    if not firebase_admin._apps:
        cred = credentials.Certificate(key_path)
        firebase_admin.initialize_app(cred)

    db = firestore.client()
    
    docs = db.collection('ready_stock').stream()
    count = 0
    
    print("--- STARTING RESERVED_QUANTITY MIGRATION ---")
    
    for doc in docs:
        data = doc.to_dict()
        if 'reserved_quantity' not in data:
            print(f"  [!] Fixing ID: {doc.id} ({data.get('name', 'Unknown')})")
            db.collection('ready_stock').document(doc.id).update({
                'reserved_quantity': 0
            })
            count += 1
            
    print(f"\n--- MIGRATION COMPLETE. Fixed {count} records. ---")

if __name__ == "__main__":
    migrate_reserved_quantity()
