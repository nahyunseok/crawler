"""
구글 스프레드시트 기반 온라인 라이선스 인증 클라이언트
Golden_Keyword 프로젝트에서 이식 후 Gemini Image Crawler에 맞게 조정
"""
import requests
import sys
import uuid
import json
import os
import base64
import hmac
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

    # 캐시 서명용 내부 시크릿.
    # ⛔ 이것만으로 완전한 보안이 되지는 않지만(클라이언트 프로그램의 한계),
    #    HWID와 조합해 HMAC 서명을 만들기 때문에 '캐시 파일을 손으로 위조해서
    #    무기한 사용'하는 가장 흔한 크랙 경로는 막을 수 있다.
    _CACHE_SECRET = "GeminiImageCrawler::license-cache::v2"
    
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
            
        except ValueError as e:
            # 서버가 JSON이 아닌 응답(구글 로그인/오류 HTML 페이지 등)을 준 경우.
            # ⛔ 이 블록은 반드시 RequestException 보다 '위'에 있어야 한다.
            #    requests 의 JSONDecodeError 는 ValueError 와 RequestException 을 동시에
            #    상속하므로, 순서가 바뀌면 JSON 오류가 '연결 실패'로 잘못 안내된다.
            #    (서버 이상이므로 캐시가 유효하면 그대로 통과시켜 준다)
            self.logger.error(f"License server returned invalid response: {e}")
            cached = self._check_cache(license_key)
            if cached:
                return cached
            return {
                "valid": False,
                "message": "라이선스 서버 응답을 해석할 수 없습니다.\n잠시 후 다시 시도해주세요.",
                "data": None,
            }

        except requests.exceptions.RequestException as e:
            # 네트워크 문제 전반(연결 실패·응답 지연·SSL 오류 등) → 로컬 캐시로 대체
            #
            # ⛔ 수정금지(DO NOT MODIFY — INTENDED)
            # 무엇: ConnectionError 하나만 잡지 않고 RequestException(상위 클래스)으로 받는다.
            # 왜:   requests.exceptions.ReadTimeout 은 ConnectionError 의 하위 클래스가 아니다.
            #       예전에는 ConnectionError 만 잡아서, 네트워크가 '느린' 경우(구글 Apps Script가
            #       10초 안에 응답하지 못한 경우)에 오프라인 캐시 폴백이 전혀 동작하지 않고
            #       '인증 오류'로 튕겨 정상 사용자가 프로그램을 못 켰다.
            # 건드리면: 지하철·공용 와이파이 등 느린 회선에서 인증 실패 문의가 다시 발생한다.
            self.logger.warning(f"License server unreachable ({type(e).__name__}). Checking local cache...")
            cached = self._check_cache(license_key)
            if cached:
                return cached
            return {
                "valid": False,
                "message": "라이선스 서버에 연결할 수 없습니다.\n인터넷 연결을 확인한 뒤 다시 시도해주세요.",
                "data": None,
            }

        except Exception as e:
            self.logger.error(f"License verification error: {e}")
            return {"valid": False, "message": f"인증 오류: {str(e)}", "data": None}

    # ──────────────────────────────────────────────────────────
    # 캐시 암호화/서명 (위조 방지)
    # ──────────────────────────────────────────────────────────
    def _cache_signing_key(self) -> bytes:
        """서명 키 = 내부 시크릿 + 이 PC의 HWID (다른 PC로 복사하면 서명이 깨진다)"""
        return hashlib.sha256(f"{self._CACHE_SECRET}:{self.hwid}".encode('utf-8')).digest()

    def _sign(self, payload: str) -> str:
        return hmac.new(self._cache_signing_key(), payload.encode('utf-8'), hashlib.sha256).hexdigest()

    def _encode_cache(self, cache_data: dict) -> str:
        """캐시 데이터를 서명 + Base64로 감싼다."""
        payload = json.dumps(cache_data, ensure_ascii=False, sort_keys=True)
        envelope = {"payload": payload, "sig": self._sign(payload)}
        return base64.b64encode(json.dumps(envelope).encode('utf-8')).decode('utf-8')

    def _decode_cache(self, content: str):
        """
        캐시 파일을 해독하고 서명을 검증한다.
        ⛔ 서명이 없거나 어긋나면 무조건 무효 처리한다.
           (예전 버전은 Base64 인코딩만 해서, 만료일을 마음대로 고쳐 넣은
            캐시 파일로 영구 무료 사용이 가능했다)
        Returns: dict or None
        """
        if not content:
            return None
        try:
            decoded = base64.b64decode(content).decode('utf-8')
            envelope = json.loads(decoded)
        except Exception:
            # 구버전 평문/무서명 캐시 → 신뢰할 수 없으므로 폐기 (재인증 유도)
            self.logger.warning("Unsigned or unreadable license cache detected. Re-activation required.")
            return None

        if not isinstance(envelope, dict) or "payload" not in envelope or "sig" not in envelope:
            self.logger.warning("License cache has no signature. Re-activation required.")
            return None

        payload = envelope.get("payload", "")
        if not hmac.compare_digest(self._sign(payload), envelope.get("sig", "")):
            self.logger.warning("License cache signature mismatch (tampered or copied).")
            return None

        try:
            return json.loads(payload)
        except Exception:
            return None

    def _read_cache_file(self):
        """캐시 파일을 읽어 검증된 dict 를 반환 (없거나 위조면 None)."""
        try:
            if not os.path.exists(self.cache_file):
                return None
            with open(self.cache_file, "r", encoding="utf-8") as f:
                return self._decode_cache(f.read().strip())
        except Exception:
            return None

    def get_cached_key(self):
        """인증창에서 이전에 쓰던 키를 미리 채워 넣기 위한 조회용."""
        cache = self._read_cache_file()
        if cache:
            return cache.get("key", "")
        return ""

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
            
            # 보안 강화: HWID 기반 HMAC 서명 + Base64 인코딩
            # (평문 노출 방지 + 파일 위조 시 즉시 탐지)
            encoded = self._encode_cache(cache_data)

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
            cache = self._read_cache_file()
            if not cache:
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
            # ⛔ 반드시 _read_cache_file() 을 써야 한다.
            #    캐시를 서명+Base64로 저장하도록 바꾼 뒤에도 여기만 평문 json.load 를
            #    쓰고 있어서, 오프라인 인증 폴백이 항상 실패하던 버그가 있었다.
            cache = self._read_cache_file()
            if not cache:
                return None

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
