import os
import json
import uuid
import hashlib
from datetime import datetime, timedelta
from src.utils.logger import get_logger
from appdirs import user_data_dir

class LicenseManager:
    def __init__(self):
        self.logger = get_logger()
        self.app_name = "GeminiImageCrawler"
        self.app_author = "User"
        
        # Determine a safe cross-platform directory for storing the license
        self.data_dir = user_data_dir(self.app_name, self.app_author)
        os.makedirs(self.data_dir, exist_ok=True)
        self.license_file = os.path.join(self.data_dir, "license.dat")
        
        self.secret_salt = "gemini_secret_salt_2026!@" # Simple salt
        self._current_license = None
        self._load_license()

    def _load_license(self):
        """Loads and parses the existing license file if it exists."""
        if not os.path.exists(self.license_file):
            return
            
        try:
            with open(self.license_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                
                # Check integrity before accepting
                if self._verify_integrity(data):
                    self._current_license = data
                else:
                    self.logger.warning("License file integrity check failed (Tampered).")
                    os.remove(self.license_file) # Remove invalid license
        except Exception as e:
            self.logger.error(f"Error loading license: {e}")

    def _verify_integrity(self, data):
        """Re-hashes the data to ensure it hasn't been manually edited."""
        stored_hash = data.get("hash")
        if not stored_hash:
            return False
            
        keys_to_hash = f"{data.get('key')}_{data.get('expiry_date')}_{self.secret_salt}"
        expected_hash = hashlib.sha256(keys_to_hash.encode()).hexdigest()
        
        return stored_hash == expected_hash

    def validate_key(self, key):
        """
        Simulates key validation via a server or algorithm.
        For this offline version, we accept specific keywords or a 16-char string 
        and assign an expiry date based on the key prefix.
        
        Rules:
        - "TRIAL-" -> 7 days
        - "PRO-" -> 365 days
        - "LIFETIME-" -> 36500 days
        - "test4321" -> 365 days (User requested)
        """
        key = key.strip()
        upper_key = key.upper()
        
        days_valid = 0
        if upper_key.startswith("TRIAL-"):
            days_valid = 7
        elif upper_key.startswith("PRO-"):
            days_valid = 365
        elif upper_key.startswith("LIFETIME-"):
            days_valid = 36500
        elif key == "test4321":  # Custom requested key (case-sensitive as typed by user, or make it insensitive if preferred. Let's make it exact)
            days_valid = 365
            upper_key = key # keep original for saving
        else:
            return False, "유효하지 않은 라이센스 키 형식입니다. (test4321 등 유효한 키를 입력하세요)"
            
        # Simulate activation
        expiry_date = (datetime.now() + timedelta(days=days_valid)).strftime("%Y-%m-%d %H:%M:%S")
        
        license_data = {
            "key": upper_key,
            "expiry_date": expiry_date,
            "activated_on": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        
        # Add hash
        hash_str = f"{key}_{expiry_date}_{self.secret_salt}"
        license_data["hash"] = hashlib.sha256(hash_str.encode()).hexdigest()
        
        # Save
        try:
            with open(self.license_file, 'w', encoding='utf-8') as f:
                json.dump(license_data, f, indent=4)
            self._current_license = license_data
            self.logger.info(f"License Activated: {key} (Expires: {expiry_date})")
            return True, "라이센스가 성공적으로 인증되었습니다!"
        except Exception as e:
            return False, f"라이센스 저장 중 오류가 발생했습니다: {e}"

    def get_license_status(self):
        """Returns the current status, expiry string, and days remaining."""
        if not self._current_license:
            return False, "미인증", 0
            
        expiry_str = self._current_license.get("expiry_date")
        if not expiry_str:
            return False, "손상된 라이센스", 0
            
        try:
            expiry_date = datetime.strptime(expiry_str, "%Y-%m-%d %H:%M:%S")
            now = datetime.now()
            
            if now > expiry_date:
                return False, "만료됨", 0
                
            days_remaining = (expiry_date - now).days
            return True, expiry_str, days_remaining
            
        except ValueError:
            return False, "날짜 형식 오류", 0

    def deactivate_license(self):
        """Removes the current license."""
        if os.path.exists(self.license_file):
            os.remove(self.license_file)
        self._current_license = None
        self.logger.info("License deactivated.")
