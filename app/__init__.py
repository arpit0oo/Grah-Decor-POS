import os
import firebase_admin
from firebase_admin import credentials, firestore
from flask import Flask
from app.config import Config


db = None


def get_db():
    """Get Firestore client instance."""
    global db
    return db


def create_app():
    """Application factory."""
    global db

    app = Flask(__name__)
    app.config.from_object(Config)

    # Initialize Firebase
    key_path = app.config['FIREBASE_KEY_PATH']
    if not os.path.isabs(key_path):
        key_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), key_path)

    if not firebase_admin._apps:
        cred = credentials.Certificate(key_path)
        firebase_admin.initialize_app(cred)

    db = firestore.client()

    # Register blueprints
    from app.routes.inventory import inventory_bp
    from app.routes.purchase import purchase_bp
    from app.routes.orders import orders_bp
    from app.routes.cashbook import cashbook_bp

    app.register_blueprint(inventory_bp)
    app.register_blueprint(purchase_bp)
    app.register_blueprint(orders_bp)
    app.register_blueprint(cashbook_bp)

    # Root redirect
    @app.route('/')
    def index():
        from flask import redirect, url_for
        return redirect(url_for('orders.orders_list'))

    return app
