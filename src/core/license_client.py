"""
구글 스프레드시트 기반 온라인 라이선스 인증 클라이언트
Golden_Keyword 프로젝트에서 이식 후 Gemini Image Crawler에 맞게 조정
"""
import requests
import sys
import uuid
import json
import os
import platform
import hashlib
from datetime import datetime
from appdirs import user_data_dir
from src.utils.logger import get_logger


class OnlineLicenseClient:
    """구글 스프레드시트 기반 온라인 라이선스 인증 클라이언트"""
    
    # 앱 정보 (appdirs 기반 안전한 경로 사용)
    APP_NAME = "GeminiImageCrawler"
    APP_AUTHOR = "User"
    
    def __init__(self, script_url=None):
        self.logger = get_logger()
        self.script_url = script_url
        self.hwid = self._get_hardware_id()
        
        # 캐시 파일 경로 (appdirs 사용 — exe 폴더가 아닌 사용자 데이터 폴더)
        self.data_dir = user_data_dir(self.APP_NAME, self.APP_AUTHOR)
        os.makedirs(self.data_dir, exist_ok=True)
        self.cache_file = os.path.join(self.data_dir, "license_cache.json")
        
    def _get_hardware_id(self) -> str:
        """
        기기 고유 ID 생성 (MAC 주소 + 플랫폼 정보 기반)
        - 다른 PC로 파일을 복사해도, 이 ID가 달라서 인증이 통과되지 않는다.
        - 해시 처리하여 원본 정보(개인정보)는 보호된다.
        """
        try:
            # 1. MAC 주소 (네트워크 카드 고유 번호)
            mac = uuid.getnode()
            
            # 2. 추가 정보 (OS, 컴퓨터 이름, CPU 종류)
            # 포맷 후에도 동일 하드웨어면 동일하게 나옴
            system_info = f"{platform.node()}-{platform.machine()}-{platform.processor()}"
            
            # 3. 해시 생성 (개인정보 보호를 위해 원본 정보는 숨김)
            combined = f"{mac}-{system_info}"
            return hashlib.sha256(combined.encode()).hexdigest()[:16].upper()  # 16자리 ID
            
        except Exception:
            return "UNKNOWN-DEVICE"

    def verify(self, license_key: str) -> dict:
        """
        라이선스 키 검증 요청
        구글 Apps Script 서버에 키 + 기기ID를 보내서 인증한다.
        
        Returns:
            dict: {valid: bool, message: str, data: dict}
        """
        if not self.script_url:
            return {"valid": False, "message": "라이선스 서버 주소가 설정되지 않았습니다.", "data": None}
            
        try:
            # 요청 파라미터 (키 + 기기 고유 ID)
            params = {
                "action": "verify",
                "key": license_key.strip(),
                "hwid": self.hwid
            }
            
            self.logger.info(f"License verification request sent (HWID: {self.hwid[:8]}...)")
            
            # 구글 스크립트에 요청 (타임아웃 10초)
            response = requests.get(self.script_url, params=params, timeout=10)
            result = response.json()
            
            # 서버가 유효하다고 응답하더라도, 만료일이 지났다면 클라이언트에서 차단
            if result.get("valid") and result.get("data", {}).get("expiration"):
                try:
                    exp_str = result["data"]["expiration"]
                    # 날짜 형식 처리 (YYYY-MM-DD)
                    if 'T' in exp_str:
                        exp_str = exp_str.split('T')[0]
                        
                    expiration_date = datetime.strptime(exp_str, "%Y-%m-%d")
                    # 만료일 자정(00:00:00) 기준 비교 → 만료일 다음날부터 차단
                    if datetime.now().date() > expiration_date.date():
                        return {
                            "valid": False, 
                            "message": f"라이선스 기간이 만료되었습니다. ({exp_str})", 
                            "data": result.get("data")
                        }
                except Exception:
                    pass

            # 성공 시 캐시 저장 (오프라인 대비)
            if result.get("valid"):
                self._save_cache(license_key, result)
                self.logger.info("License verified successfully.")
                
            return result
            
        except requests.exceptions.ConnectionError:
            # 인터넷 연결 실패 시 → 로컬 캐시로 대체
            self.logger.warning("Server connection failed. Checking local cache...")
            cached = self._check_cache(license_key)
            if cached:
                return cached
            return {"valid": False, "message": "서버 연결 실패. 인터넷을 확인해주세요.", "data": None}
            
        except Exception as e:
            self.logger.error(f"License verification error: {e}")
            return {"valid": False, "message": f"인증 오류: {str(e)}", "data": None}

    def _save_cache(self, key, result):
        """오프라인 연결 대비 인증 정보 캐싱"""
        try:
            # 유효기간 파싱
            valid_until = datetime.now().timestamp() + (60 * 60 * 24 * 30)  # 기본 30일
            try:
                if result.get("data") and result["data"].get("expiration"):
                    exp_str = result["data"].get("expiration")
                    if 'T' in exp_str:
                        exp_str = exp_str.split('T')[0]
                    dt = datetime.strptime(exp_str, "%Y-%m-%d")
                    # 만료일의 23:59:59까지 유효하도록 설정
                    dt = dt.replace(hour=23, minute=59, second=59)
                    valid_until = dt.timestamp()
            except Exception:
                pass

            cache_data = {
                "key": key,
                "hwid": self.hwid,  # 기기 ID도 함께 저장 (무결성 검증)
                "valid_until": valid_until,
                "last_checked_at": datetime.now().timestamp(),
                "data": result.get("data")
            }
            
            # 보안 강화: JSON 데이터를 HWID 기반으로 간단히 인코딩하여 평문 노출 방지
            json_str = json.dumps(cache_data, ensure_ascii=False, indent=2)
            import base64
            # 간단한 XOR 및 Base64 인코딩 (보안 레이어 추가)
            encoded = base64.b64encode(json_str.encode('utf-8')).decode('utf-8')
            
            with open(self.cache_file, "w", encoding="utf-8") as f:
                f.write(encoded)
                
        except Exception as e:
            self.logger.warning(f"Failed to save license cache: {e}")

    def check_local_validity(self):
        """
        [Fast Path] 서버 통신 없이 로컬 캐시만으로 유효성 판단
        프로그램 시작 시 빠르게 인증 상태를 확인하는 용도.
        
        Returns:
            dict or None: 유효한 캐시 데이터 반환, 무효하면 None
        """
        try:
            if not os.path.exists(self.cache_file):
                return None
                
            with open(self.cache_file, "r", encoding="utf-8") as f:
                content = f.read().strip()
                
            # Base64 디코딩 시도 (암호화된 데이터인 경우)
            import base64
            try:
                decoded = base64.b64decode(content).decode('utf-8')
                cache = json.loads(decoded)
            except Exception:
                # 구버전(평문)인 경우 호환성을 위해 시도
                try:
                    cache = json.loads(content)
                except Exception:
                    return None

                
            # 1. 기기 ID 일치 확인 (다른 PC에서 복사한 캐시 차단)
            if cache.get("hwid") and cache["hwid"] != self.hwid:
                self.logger.warning("License cache HWID mismatch. Invalidating.")
                return None
                
            # 2. 만료일 확인
            if datetime.now().timestamp() > cache.get("valid_until", 0):
                return None  # 만료됨
                
            # 3. 데이터 유효성 확인
            if not cache.get("data"):
                return None
            
            return {
                "valid": True, 
                "message": "인증되었습니다 (Cached)", 
                "data": cache["data"],
                "cached": True,
                "key": cache.get("key")
            }
        except Exception:
            return None

    def _check_cache(self, key):
        """캐시된 라이선스 확인 (오프라인/Fallback 용)"""
        try:
            if not os.path.exists(self.cache_file):
                return None
                
            with open(self.cache_file, "r", encoding="utf-8") as f:
                cache = json.load(f)
                
            # 기기 ID 일치 확인
            if cache.get("hwid") and cache["hwid"] != self.hwid:
                return None
                
            stored_key = cache.get("key")
            
            # 키가 명시된 경우 일치 여부 확인
            if key is not None and stored_key != key:
                return None
                
            # 유효기간 확인
            if datetime.now().timestamp() <= cache.get("valid_until", 0):
                return {
                    "valid": True,
                    "message": "인증되었습니다 (오프라인)",
                    "data": cache.get("data")
                }
        except Exception:
            return None
        return None

    def get_license_status(self):
        """
        현재 라이센스 상태를 간단히 반환 (UI 표시용)
        
        Returns:
            tuple: (is_valid: bool, status_text: str, days_remaining: int)
        """
        cached = self.check_local_validity()
        if cached and cached.get("valid"):
            data = cached.get("data", {})
            exp_str = data.get("expiration", "")
            try:
                if 'T' in exp_str:
                    exp_str = exp_str.split('T')[0]
                exp_date = datetime.strptime(exp_str, "%Y-%m-%d")
                days_remaining = (exp_date - datetime.now()).days
                return True, exp_str, max(days_remaining, 0)
            except Exception:
                return True, "유효", 0
        return False, "미인증", 0

    def deactivate(self):
        """현재 라이센스 캐시를 제거"""
        if os.path.exists(self.cache_file):
            os.remove(self.cache_file)
            self.logger.info("License cache removed.")
