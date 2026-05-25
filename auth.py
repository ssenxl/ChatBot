import os
import json
import time
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from azure.identity import ClientSecretCredential, DefaultAzureCredential
from azure.core.credentials import AccessToken
import msal
from dotenv import load_dotenv

# โหลด environment variables จาก .env file
load_dotenv()

class AzureTokenManager:
    """จัดการ Azure Token อัตโนมัติ"""
    
    def __init__(self, tenant_id: str, client_id: str, client_secret: Optional[str] = None):
        self.tenant_id = tenant_id
        self.client_id = client_id
        self.client_secret = client_secret
        self.token_cache = {}
        self.scope = ["https://analysis.windows.net/powerbi/api/.default"]
        
    def get_cached_token(self, cache_key: str) -> Optional[str]:
        """ดึง token จาก cache ถ้ายังไม่หมดอายุ"""
        if cache_key in self.token_cache:
            token_data = self.token_cache[cache_key]
            expires_at = datetime.fromisoformat(token_data['expires_at'])
            
            # Refresh 5 นาทีก่อนหมดอายุ
            if datetime.now() < expires_at - timedelta(minutes=5):
                return token_data['token']
            else:
                del self.token_cache[cache_key]
        
        return None
    
    def cache_token(self, cache_key: str, token: str, expires_in: int):
        """เก็บ token ไว้ใน cache"""
        expires_at = datetime.now() + timedelta(seconds=expires_in)
        self.token_cache[cache_key] = {
            'token': token,
            'expires_at': expires_at.isoformat()
        }
    
    def get_token_client_secret(self) -> str:
        """ขอ token ด้วย Client Secret"""
        cache_key = f"client_secret_{self.tenant_id}_{self.client_id}"
        
        # ลองดึงจาก cache ก่อน
        cached_token = self.get_cached_token(cache_key)
        if cached_token:
            return cached_token
        
        # ขอ token ใหม่
        credential = ClientSecretCredential(
            tenant_id=self.tenant_id,
            client_id=self.client_id,
            client_secret=self.client_secret
        )
        
        token = credential.get_token("https://analysis.windows.net/powerbi/api")
        
        # เก็บใน cache
        self.cache_token(cache_key, token.token, token.expires_on - int(time.time()))
        
        return token.token
    
    def get_token_managed_identity(self) -> str:
        """ขอ token ด้วย Managed Identity (สำหรับ Azure VM/App Service)"""
        cache_key = "managed_identity_powerbi"
        
        # ลองดึงจาก cache ก่อน
        cached_token = self.get_cached_token(cache_key)
        if cached_token:
            return cached_token
        
        # ขอ token ใหม่
        credential = DefaultAzureCredential()
        token = credential.get_token("https://analysis.windows.net/powerbi/api")
        
        # เก็บใน cache
        self.cache_token(cache_key, token.token, token.expires_on - int(time.time()))
        
        return token.token
    
    def get_token_interactive(self) -> str:
        """ขอ token แบบ Interactive (สำหรับการพัฒนา)"""
        cache_key = f"interactive_{self.tenant_id}_{self.client_id}"
        
        # ลองดึงจาก cache ก่อน
        cached_token = self.get_cached_token(cache_key)
        if cached_token:
            return cached_token
        
        # สร้าง MSAL app
        app = msal.PublicClientApplication(
            client_id=self.client_id,
            authority=f"https://login.microsoftonline.com/{self.tenant_id}"
        )
        
        # ขอ token แบบ interactive
        result = app.acquire_token_interactive(scopes=self.scope)
        
        if "access_token" in result:
            # เก็บใน cache
            self.cache_token(cache_key, result["access_token"], result["expires_in"])
            return result["access_token"]
        else:
            raise Exception(f"ไม่สามารถขอ token ได้: {result.get('error', 'Unknown error')}")
    
    def get_token_device_code(self) -> str:
        """ขอ token ด้วย Device Code Flow"""
        cache_key = f"device_{self.tenant_id}_{self.client_id}"
        
        # ลองดึงจาก cache ก่อน
        cached_token = self.get_cached_token(cache_key)
        if cached_token:
            return cached_token
        
        # สร้าง MSAL app
        app = msal.PublicClientApplication(
            client_id=self.client_id,
            authority=f"https://login.microsoftonline.com/{self.tenant_id}"
        )
        
        # ขอ device code
        flow = app.initiate_device_flow(scopes=self.scope)
        
        if "user_code" not in flow:
            raise ValueError("ไม่สามารถสร้าง device flow ได้")
        
        print(f"กรุณาไปที่: {flow['verification_uri']}")
        print(f"และใส่ code: {flow['user_code']}")
        
        # ขอ token
        result = app.acquire_token_by_device_flow(flow)
        
        if "access_token" in result:
            # เก็บใน cache
            self.cache_token(cache_key, result["access_token"], result["expires_in"])
            return result["access_token"]
        else:
            raise Exception(f"ไม่สามารถขอ token ได้: {result.get('error', 'Unknown error')}")
    
    def auto_detect_and_get_token(self) -> str:
        """ตรวจสอบและขอ token อัตโนมัติตาม environment"""
        
        # 1. ลอง Managed Identity ก่อน (สำหรับ Azure environment)
        try:
            if os.getenv('AZURE_CLIENT_ID') or os.getenv('IDENTITY_ENDPOINT'):
                return self.get_token_managed_identity()
        except:
            pass
        
        # 2. ลอง Client Secret ถ้ามี
        if self.client_secret:
            try:
                return self.get_token_client_secret()
            except:
                pass
        
        # 3. ลอง Interactive สำหรับ development
        try:
            return self.get_token_interactive()
        except:
            pass
        
        # 4. สุดท้ายลอง Device Code
        try:
            return self.get_token_device_code()
        except:
            raise Exception("ไม่สามารถขอ Azure token ได้ด้วยวิธีใดๆ")
    
    def save_cache_to_file(self, filepath: str):
        """บันทึก cache ลงไฟล์"""
        try:
            with open(filepath, 'w') as f:
                json.dump(self.token_cache, f)
        except Exception as e:
            print(f"ไม่สามารถบันทึก cache: {e}")
    
    def load_cache_from_file(self, filepath: str):
        """โหลด cache จากไฟล์"""
        try:
            if os.path.exists(filepath):
                with open(filepath, 'r') as f:
                    self.token_cache = json.load(f)
        except Exception as e:
            print(f"ไม่สามารถโหลด cache: {e}")

# Environment variables สำหรับ auto-detection
def get_azure_credentials_from_env() -> Dict[str, str]:
    """ดึง Azure credentials จาก environment variables"""
    return {
        'tenant_id': os.getenv('AZURE_TENANT_ID', ''),
        'client_id': os.getenv('AZURE_CLIENT_ID', ''),
        'client_secret': os.getenv('AZURE_CLIENT_SECRET', '')
    }
