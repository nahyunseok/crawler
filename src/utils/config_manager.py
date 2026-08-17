import json
import os
from src.utils.logger import get_logger

CONFIG_DIR_NAME = "config"
CONFIG_FILE_NAME = "settings.json"


def _is_writable_dir(directory):
    """해당 폴더에 실제로 파일을 쓸 수 있는지 '써보고' 확인한다."""
    try:
        os.makedirs(directory, exist_ok=True)
        probe = os.path.join(directory, ".write_test")
        with open(probe, "w", encoding="utf-8") as f:
            f.write("ok")
        os.remove(probe)
        return True
    except Exception:
        return False


def resolve_config_path(config_path=None):
    """
    설정 파일 경로를 정한다. 로거(_resolve_log_dir)와 같은 전략이다.
    1순위: 실행 폴더의 config/  (사용자가 직접 열어보고 고칠 수 있어 편하다)
    2순위: 사용자 데이터 폴더    (Program Files 처럼 쓰기 권한이 없는 곳에 설치된 경우)

    ⛔ 수정금지(DO NOT MODIFY — INTENDED)
    무엇: os.path.abspath() 로 끝내지 않고 '쓰기 가능 여부'를 실제로 검사한다.
    왜:   abspath 는 현재 작업 폴더(cwd) 기준으로 경로를 붙일 뿐, 권한을 보장하지 않는다.
          예전 코드의 주석은 "실행 위치가 바뀌어도 안전"이라고 적혀 있었지만 사실이 아니었고,
          권한 없는 폴더에 설치하면 설정 저장이 매번 조용히 실패했다(로그만 남고 UI는 성공처럼 보임).
    건드리면: PC방·회사 PC 등 제한된 환경에서 설정이 저장되지 않는 문의가 다시 발생한다.
    """
    if config_path:
        # 호출부가 경로를 명시한 경우는 그 의도를 그대로 존중한다
        return os.path.abspath(config_path)

    primary = os.path.join(os.getcwd(), CONFIG_DIR_NAME)
    if _is_writable_dir(primary):
        return os.path.join(primary, CONFIG_FILE_NAME)

    try:
        from appdirs import user_data_dir
        fallback = os.path.join(user_data_dir("GeminiImageCrawler", "User"), CONFIG_DIR_NAME)
        os.makedirs(fallback, exist_ok=True)
        return os.path.join(fallback, CONFIG_FILE_NAME)
    except Exception:
        # 최후의 수단 — 어디에도 쓸 수 없으면 기존 동작을 유지한다
        return os.path.join(primary, CONFIG_FILE_NAME)


def resolve_data_dir(subdir_name):
    """
    사용자 데이터를 저장할 폴더를 정한다 (results 등).
    1순위: 실행 폴더  2순위: 사용자 데이터 폴더 — 로거·설정과 동일한 전략이다.

    ⛔ 수정금지(DO NOT MODIFY — INTENDED)
    무엇: 설정·로그와 '같은 규칙'으로 쓰기 가능한 폴더를 찾는다.
    왜:   예전에는 results 만 os.getcwd() 에 고정되어 있었다. 설정과 로그는 권한이 없으면
          사용자 데이터 폴더로 대체되는데 results 만 대체되지 않아, 쓰기 권한 없는 위치
          (예: Program Files, 네트워크 드라이브)에서 실행하면 수집 자체가 실패했다.
    건드리면: 제한된 PC 에서 '수집은 되는데 저장이 안 되는' 문의가 다시 발생한다.
    """
    primary = os.path.join(os.getcwd(), subdir_name)
    if _is_writable_dir(primary):
        return primary
    try:
        from appdirs import user_data_dir
        fallback = os.path.join(user_data_dir("GeminiImageCrawler", "User"), subdir_name)
        os.makedirs(fallback, exist_ok=True)
        return fallback
    except Exception:
        return primary


# 확장자 체크박스(설정 키) → 실제 허용 확장자 목록
# ⛔ 순서를 바꾸거나 항목을 늘릴 때는 UI 체크박스도 함께 고쳐야 한다.
EXT_SETTING_MAP = (
    ("ext_jpg", ('.jpg', '.jpeg')),
    ("ext_png", ('.png',)),
    ("ext_webp", ('.webp',)),
    ("ext_gif", ('.gif',)),
)


def allowed_extensions(config_manager):
    """
    사용자가 UI에서 켜 둔 '허용 확장자' 목록을 반환한다. (예: ('.jpg', '.jpeg', '.png'))

    ⛔ 수정금지(DO NOT MODIFY — INTENDED): 이 목록은 여기 '한 곳'에서만 만든다.
    무엇: 크롤러(주소 기준 필터)와 다운로더(실제 파일 포맷 기준 필터)가 같은 함수를 쓴다.
    왜:   예전에는 crawler_engine 안에서만 목록을 만들었고, 다운로더는 검사하지 않았다.
          그래서 확장자가 없는 주소(예: /photo?id=1)는 화이트리스트를 그냥 통과한 뒤
          PIL 이 판별한 실제 포맷으로 저장되어, GIF 체크를 껐는데도 .gif 가 저장됐다.
          (화면 표시와 실제 동작이 어긋나는 대표적인 사고)
    건드리면: 확장자 체크박스가 '주소에 확장자가 있는 경우에만' 동작하는 반쪽 필터로 되돌아간다.
    """
    exts = []
    for key, values in EXT_SETTING_MAP:
        if config_manager.get(key, key != "ext_gif"):   # GIF 만 기본 꺼짐
            exts.extend(values)
    return tuple(exts)


def delay_bounds(delay_level):
    """
    UI의 '안전 딜레이' 단계(1~5) → 실제 요청 간격(최소, 최대)초.

    ⛔ 수정금지(DO NOT MODIFY — INTENDED): 이 공식은 여기 '한 곳'에만 있어야 한다.
    왜: 화면에 보이는 값과 실제 동작이 다른 사고를 막기 위함이다(표시=동작 일치).
        예전에는 이 계산이 main_window.save_settings 안에만 있어서, 다른 곳에서
        같은 계산을 다시 적으면 두 벌이 어긋날 수 있었다.
        딜레이는 계정 정지·IP 차단과 직결되므로 절대 0 이 되어선 안 된다(전역수칙 6).
    """
    level = max(float(delay_level), 1.0)   # 0 이하가 들어와도 최소 1단계로 보정
    minimum = level * 0.5
    return minimum, minimum + 1.0


class ConfigManager:
    def __init__(self, config_path=None):
        self.config_path = resolve_config_path(config_path)
        self.logger = get_logger()
        # 마지막 저장 실패 사유 (UI가 사용자에게 알려주기 위해 읽는다 — 침묵 실패 금지)
        self.last_error = None
        self.default_config = {
            # 이미지 필터
            "min_width": 100,
            "min_height": 100,
            "ext_jpg": True,
            "ext_png": True,
            "ext_webp": True,
            "ext_gif": False,
            "ext_allow_base64": True,          # 페이지에 박혀 있는 Base64 이미지 수집 여부
            "exclude_keywords": "logo, icon, button, tracker, pixel, banner",
            "include_keywords": "",
            "max_image_mb": 20,                # 이미지 1장 최대 용량(MB) — 메모리 폭탄 방지

            # 브라우저 동작
            "headless": True,
            "timeout": 30,
            "user_agent_rotation": True,
            "random_delay_min": 1.0,
            "random_delay_max": 2.0,
            "delay_level": 2,
            # 한 페이지에서 스크롤할 최대 횟수. 0 = 자동(기본 상한까지)
            # ⛔ 0 을 '스크롤 0번' 으로 해석하면 지연로딩 이미지가 전멸한다 — _max_scrolls() 참조
            "max_scrolls": 0,

            # 수집 정책
            "respect_robots": True,            # robots.txt 준수 (전역수칙 9)
            "use_resume": True,                # 이어받기(중복 제외)
            "manual_login": False,
            "login_wait": 30,
            "use_pagination": False,
            "pagination_selector": "",
            "max_pagination_pages": 30,        # '다음 페이지' 최대 순회 수

            # 수집 범위 — 예전에는 저장하지 않아 프로그램을 다시 켜면 매번 초기화됐다.
            # (다른 설정은 다 기억하는데 이 두 개만 잊어버려 일관성이 없었다)
            "use_scope": False,                # '특정 영역만 수집' 사용 여부
            "scope_selector": "",              # 그 영역의 CSS 선택자
            "crawl_depth": 1,                  # 1=현재 페이지만, 2=링크까지
        }
        self.config = self.load_config()

    def load_config(self):
        """
        설정 파일을 읽어온다.
        ⛔ 기본값과 '병합'해서 반환한다. 프로그램 업데이트로 새 설정 키가 늘어났을 때
           예전 settings.json 에 그 키가 없어서 기능이 조용히 꺼지는 것을 막기 위함이다.
        """
        if not os.path.exists(self.config_path):
            self.logger.info("Config file not found. Creating default config.")
            merged = dict(self.default_config)
            self.save_config(merged)
            return merged

        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                loaded = json.load(f)
            if not isinstance(loaded, dict):
                raise ValueError("settings.json is not a JSON object")

            merged = dict(self.default_config)
            merged.update(loaded)

            # 새로 추가된 기본 키가 있으면 파일에도 반영해 둔다.
            # (개수 비교가 아니라 '키 존재 여부'로 판단해야 한다 —
            #  없어진 키와 새 키의 개수가 우연히 같으면 개수 비교는 놓친다)
            missing_keys = set(self.default_config) - set(loaded)
            if missing_keys:
                self.logger.info(f"Config migrated with new keys: {sorted(missing_keys)}")
                self.save_config(merged)
            return merged
        except Exception as e:
            self.logger.error(f"Failed to load config: {e}")
            return dict(self.default_config)

    def save_config(self, config):
        """
        설정을 파일에 저장한다.

        ⛔ 수정금지(DO NOT MODIFY — INTENDED): 반드시 '임시 파일 → os.replace' 방식으로 쓴다.
        무엇: 같은 폴더에 .tmp 파일을 먼저 완성한 뒤 원본 위로 원자적으로 교체한다.
        왜:   원본 파일을 열어 직접 덮어쓰던 방식은, 쓰는 도중에 프로그램이 강제 종료되면
              settings.json 이 반쪽만 남아 JSON 파싱 자체가 깨졌다(설정 전체 초기화).
              os.replace 는 윈도우에서도 원자적이라 '완성된 파일'만 사용자에게 노출된다.
        건드리면: 설정 파일 손상으로 사용자의 필터 설정이 통째로 날아가는 사고가 재발한다.
        """
        try:
            parent = os.path.dirname(self.config_path)
            if parent:
                os.makedirs(parent, exist_ok=True)

            tmp_path = f"{self.config_path}.tmp"
            with open(tmp_path, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=4, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())  # 디스크에 실제로 기록될 때까지 대기
            os.replace(tmp_path, self.config_path)

            self.config = config
            self.last_error = None
            return True
        except Exception as e:
            # ⛔ 침묵 실패 금지: 로그만 남기면 사용자는 저장된 줄 안다.
            #    last_error 에 사유를 남겨 UI가 화면에 띄울 수 있게 한다.
            self.logger.error(f"Failed to save config: {e}")
            self.last_error = str(e)
            # 메모리에는 반영해 둔다 — 이번 실행 동안은 설정이 동작해야 한다
            self.config = config
            return False

    def get(self, key, default=None):
        """Retrieves a configuration value."""
        return self.config.get(key, self.default_config.get(key, default))

    def set(self, key, value):
        """설정값 1개를 저장한다. (여러 개를 한꺼번에 바꿀 때는 set_many 를 쓸 것)

        Returns: bool — 파일 저장 성공 여부
        """
        return self.set_many({key: value})

    def set_many(self, values):
        """
        여러 설정값을 바꾸고 '파일에는 딱 한 번만' 저장한다.

        ⛔ 수정금지(DO NOT MODIFY — INTENDED)
        무엇: dict 를 받아 메모리에 모두 반영한 뒤 save_config 를 1회만 호출한다.
        왜:   UI의 save_settings() 는 18개 항목을 저장하는데, 예전처럼 set() 을 18번 부르면
              settings.json 을 18번 덮어썼다. 슬라이더를 움직일 때마다 이게 반복되어
              불필요한 디스크 쓰기가 폭증했고, 쓰기 도중 종료 시 손상 위험도 18배였다.
        건드리면: 설정 저장 1회가 다시 파일 쓰기 18회로 늘어난다.

        Returns: bool — 파일 저장 성공 여부 (UI가 실패를 사용자에게 알리는 데 쓴다)
        """
        if not values:
            return True          # 바꿀 게 없으면 '실패'가 아니다
        merged = dict(self.config)
        merged.update(values)
        return self.save_config(merged)
