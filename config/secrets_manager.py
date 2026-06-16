"""
Secrets Manager - Secure handling of sensitive configuration
Yeh file saare passwords, API keys, aur tokens ko safely manage karti hai
"""

import os
import json
import base64
from pathlib import Path
from typing import Optional, Dict, Any
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from dotenv import load_dotenv

class SecretsManager:
    """
    Centralized Secrets Management Class
    
    Concept: Jaise bank ka vault, isme saare sensitive data rakhein ge
    Yeh class 3 tarah se secrets read karegi:
    1. Environment variables (.env file)
    2. Encrypted secrets file (extra security ke liye)
    3. Direct values (development ke liye)
    """
    
    def __init__(self, env_file: str = ".env"):
        """
        Initialize Secrets Manager
        
        Concept: Jab app start hoti hai toh sabse pehle yeh .env file load karegi
        """
        self.env_file = env_file
        self._secrets_cache = {}  # Cache for performance
        self._load_env_file()
        self._setup_encryption()
    
    def _load_env_file(self):
        """
        .env file load karo
        
        Concept: .env file mein saare secrets plain text mein hote hain
        lekin yeh file kabhi GitHub par upload nahi hoti (yeh rule hai!)
        """
        env_path = Path('.') / self.env_file
        if env_path.exists():
            load_dotenv(dotenv_path=env_path)
            print(f"✅ .env file loaded from: {env_path}")
        else:
            print(f"⚠️ .env file not found at: {env_path}")
            print("   Creating .env from .env.example...")
            self._create_env_from_example()
    
    def _create_env_from_example(self):
        """
        Agar .env nahi hai toh .env.example se create karo
        
        Concept: .env.example template hai jisme dummy values hoti hain
        Developer copy karke apni real values daalta hai
        """
        example_path = Path('.') / '.env.example'
        env_path = Path('.') / self.env_file
        
        if example_path.exists():
            import shutil
            shutil.copy(example_path, env_path)
            print(f"✅ Created .env from .env.example")
            print("⚠️ Please update .env with real values!")
    
    def _setup_encryption(self):
        """
        Extra security ke liye encryption setup
        
        Concept: Kuch secrets ko encrypted bhi store kar sakte hain
        Taake agar koi .env file dekh bhi le toh smjh na aaye
        """
        encryption_key = os.getenv('SECRETS_ENCRYPTION_KEY')
        if encryption_key:
            # Encryption key ko bytes mein convert karo
            key = base64.urlsafe_b64decode(encryption_key)
            self.cipher = Fernet(key)
            print("🔐 Encryption enabled for secrets")
        else:
            self.cipher = None
            print("ℹ️ Encryption disabled (set SECRETS_ENCRYPTION_KEY to enable)")
    
    def get_secret(self, key: str, default: Any = None, encrypted: bool = False) -> Any:
        """
        Secret retrieve karo
        
        Concept: Yeh method pehle cache mein dekhegi, agar nahi mila toh .env se read karegi
        
        Example:
            db_password = secrets_manager.get_secret('DB_PASSWORD')
            openai_key = secrets_manager.get_secret('OPENAI_API_KEY')
        """
        # Pehle cache check karo (performance ke liye)
        if key in self._secrets_cache:
            return self._secrets_cache[key]
        
        # .env se read karo
        value = os.getenv(key)
        
        # Agar encrypted hai toh decrypt karo
        if encrypted and value and self.cipher:
            try:
                value = self.cipher.decrypt(value.encode()).decode()
            except Exception as e:
                print(f"⚠️ Failed to decrypt {key}: {e}")
        
        # Cache mein store karo (taake baar-baar na padhna pade)
        if value is not None:
            self._secrets_cache[key] = value
        
        return value if value is not None else default
    
    def get_required_secret(self, key: str) -> str:
        """
        Required secret - agar nahi mila toh error throw karega
        
        Concept: Kuch secrets mandatory hote hain (jaise database password)
        Agar wo missing hain toh app start hi nahi honi chahiye
        """
        value = self.get_secret(key)
        if value is None:
            raise ValueError(f"❌ Required secret not found: {key}")
        return value
    
    def get_database_config(self) -> Dict[str, str]:
        """
        Database configuration retrieve karo
        
        Concept: Saare DB-related secrets ek saath lao
        """
        return {
            'host': self.get_secret('DB_HOST', 'localhost'),
            'port': self.get_secret('DB_PORT', '5432'),
            'database': self.get_secret('DB_NAME', 'technify'),
            'user': self.get_required_secret('DB_USER'),
            'password': self.get_required_secret('DB_PASSWORD'),
        }
    
    def get_redis_config(self) -> Dict[str, str]:
        """
        Redis configuration retrieve karo
        """
        return {
            'host': self.get_secret('REDIS_HOST', 'localhost'),
            'port': self.get_secret('REDIS_PORT', '6379'),
            'password': self.get_secret('REDIS_PASSWORD', ''),
            'db': self.get_secret('REDIS_DB', '0'),
        }
    
    def get_openai_config(self) -> Dict[str, str]:
        """
        OpenAI API configuration
        """
        return {
            'api_key': self.get_required_secret('OPENAI_API_KEY'),
            'model': self.get_secret('OPENAI_MODEL', 'gpt-4'),
        }
    
    def validate_all_secrets(self) -> bool:
        """
        Saare required secrets check karo
        
        Concept: App start hone se pehle check karein ke saari keys exist karti hain
        Agar koi missing hai toh early error milega
        """
        required_secrets = [
            'OPENAI_API_KEY',
            'DB_USER', 
            'DB_PASSWORD',
            'JWT_SECRET_KEY',
        ]
        
        missing = []
        for secret in required_secrets:
            if not self.get_secret(secret):
                missing.append(secret)
        
        if missing:
            print(f"❌ Missing required secrets: {', '.join(missing)}")
            return False
        
        print("✅ All required secrets validated!")
        return True
    
    def reload(self):
        """
        Secrets reload karo (cache clear karke)
        
        Concept: Agar .env file change ho toh app restart kiye bina reload kar sakte hain
        """
        self._secrets_cache = {}
        self._load_env_file()
        print("🔄 Secrets reloaded")


# Singleton instance (poori app mein ek hi instance use hogi)
_secrets_manager = None

def get_secrets_manager() -> SecretsManager:
    """
    Singleton pattern - poori app mein ek hi instance
    
    Concept: Ek hi secrets manager poori app mein use karo
    Taake saari jagah same secrets use ho
    """
    global _secrets_manager
    if _secrets_manager is None:
        _secrets_manager = SecretsManager()
    return _secrets_manager