import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-fallback-secret'
    FIREBASE_KEY_PATH = os.environ.get('FIREBASE_KEY_PATH') or 'serviceAccountKey.json'
