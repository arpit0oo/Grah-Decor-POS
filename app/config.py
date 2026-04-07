import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    SECRET_KEY = os.getenv('SECRET_KEY', 'dev-secret-key')
    FIREBASE_KEY_PATH = os.getenv('FIREBASE_KEY_PATH', 'serviceAccountKey.json')
