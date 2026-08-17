import time
import os
import random
import re
import hashlib
import traceback
from urllib.parse import urljoin, urlparse, urldefrag, urlunparse
from urllib import robotparser
import undetected_chromedriver as uc
# ⛔ fake_useragent 를 쓰지 않는다(DO NOT RE-ADD — INTENDED).
#    browsers=['chrome'] 로 요청해도 20회 모두 Edge UA 를 돌려주고, 내부 조회가 실패해
#    고정된 fallback 하나만 반복 반환했다(=로테이션 아님). 게다가 그 UA 의 버전(122)이
#    실제 크롬(151)과 달라, 봇 감지에 가장 쉽게 걸리는 모순 신호를 만들었다.
#    → build_user_agent() 에서 '실제 설치된 크롬 버전' 기반으로 UA 를 만든다.
from bs4 import BeautifulSoup
from src.utils.logger import get_logger
from src.utils.config_manager import allowed_extensions

# --- Monkeypatch for undetected_chromedriver shutdown error ---
# ⛔ 수정금지(DO NOT MODIFY / DO NOT REMOVE — INTENDED)
# 무엇: uc.Chrome.__del__ 을 감싸서 종료 시 예외를 삼킨다.
# 왜: 파이썬 GC가 "Exception ignored in: <function Chrome.__del__>" 와
#     "[WinError 6] The handle is invalid" 를 콘솔에 뱉는 것을 막기 위함.
# 건드리면: 윈도우에서 프로그램 종료 시마다 사용자에게 빨간 에러가 노출된다.
original_chrome_del = uc.Chrome.__del__
def patched_chrome_del(self):
    try:
        original_chrome_del(self)
    except Exception:
        pass # Gracefully ignore standard cleanup exceptions
uc.Chrome.__del__ = patched_chrome_del
# -------------------------------------------------------------

# 이미지로 오인하기 쉬운 '플레이스홀더' 판별 키워드
# (지연로딩 사이트는 src 에 투명 1x1 이미지를 넣고 진짜 주소는 data-src/srcset 에 둔다)
PLACEHOLDER_HINTS = ('placeholder', 'blank.', 'spacer', 'loading', 'lazy-load', 'dummy', 'noimage', 'no_image')

# 이미지 주소가 들어있을 수 있는 속성들 (우선순위 순서 — 앞쪽이 '진짜'일 확률이 높다)
LAZY_SRC_ATTRS = (
    'data-src', 'data-original', 'data-lazy-src', 'data-lazy',
    'data-echo', 'data-url', 'data-image', 'data-hi-res-src',
    'data-actualsrc', 'data-original-src', 'src',
)

# 주소만 보고 '이미지 파일'로 판단할 수 있는 확장자 (화이트리스트 검사 대상)
KNOWN_IMG_EXTS = ('.jpg', '.jpeg', '.png', '.webp', '.gif', '.svg', '.bmp')

# 링크 큐에 넣으면 안 되는 파일 확장자 (문서/압축/미디어 + 이미지 자체)
# ⛔ 이미지 확장자는 KNOWN_IMG_EXTS 를 재사용한다. 예전에는 양쪽에 따로 적어 두어
#    한쪽에 확장자를 추가해도 다른 쪽은 그대로 남는 어긋남이 생길 수 있었다(DRY).
NON_PAGE_EXTS = (
    '.pdf', '.zip', '.rar', '.7z', '.exe', '.dmg', '.hwp', '.doc', '.docx',
    '.xls', '.xlsx', '.ppt', '.pptx', '.mp3', '.mp4', '.avi', '.mov', '.mkv',
    '.ico', '.css', '.js',
) + KNOWN_IMG_EXTS
# 페이지 로딩 대기 시간의 하한(초). 사용자가 설정을 너무 짧게 줄여도 정상 페이지가 실패하지 않게 한다.
MIN_PAGE_LOAD_TIMEOUT = 5
# 스크롤 진행 상황을 몇 번마다 알릴지 (매번 알리면 로그가 같은 줄로 도배된다)
SCROLL_LOG_INTERVAL = 10
# 한 페이지에서 스크롤할 기본 최대 횟수 (무한 스크롤 페이지에서 영원히 내려가지 않도록)
DEFAULT_MAX_SCROLLS = 250
# 한 번의 수집에서 방문할 최대 페이지 수 (깊이 2단계 폭주 방지)
# ⛔ 수정금지(DO NOT MODIFY / DO NOT REMOVE — INTENDED)
# 왜: 깊이 2단계에서는 첫 페이지의 링크 개수만큼 페이지를 방문한다. 링크가 수백 개인
#     사이트에서는 한 번 [수집 시작]을 누르면 몇 시간 동안 대상 서버에 요청이 계속 나갔다.
#     상한이 없으면 사용자도 멈출 생각을 못 하고, 대상 사이트에는 과부하가 된다(전역수칙 9).
MAX_PAGES_PER_CRAWL = 100

# MIME 타입 → 확장자 (data URI 파일명 생성용)
MIME_TO_EXT = {
    'jpeg': 'jpg', 'jpg': 'jpg', 'png': 'png', 'gif': 'gif',
    'webp': 'webp', 'bmp': 'bmp', 'svg+xml': 'svg',
}


class DriverSetupError(Exception):
    """
    크롬 드라이버 준비 실패 예외.
    user_message 에는 '사용자에게 그대로 보여줘도 되는 한국어 안내'가 담긴다.
    (상용 프로그램이라 원인별 대처법을 구체적으로 알려주는 것이 목적)
    """
    def __init__(self, user_message, original_error=None):
        super().__init__(user_message)
        self.user_message = user_message
        self.original_error = original_error


class CrawlerEngine:
    def __init__(self, config_manager):
        self.logger = get_logger()
        self.config = config_manager
        self.driver = None
        # 다운로더가 재사용할 브라우저 세션 쿠키 (수동 로그인 결과를 넘겨주기 위함)
        self.session_cookies = []
        # robots.txt 파서 캐시 (도메인별 1회만 조회)
        self._robots_cache = {}

    # ──────────────────────────────────────────────────────────
    # 드라이버 준비
    # ──────────────────────────────────────────────────────────
    def _page_load_timeout(self):
        """
        페이지 로딩 최대 대기 시간(초).

        ⛔ 수정금지(DO NOT MODIFY — INTENDED): 숫자를 코드에 직접 적지 말고 설정에서 읽는다.
        무엇: settings.json 의 timeout 값을 실제로 사용한다.
        왜:   예전에는 set_page_load_timeout(30) 이 두 곳에 하드코딩되어 있었고,
              timeout 설정은 아무도 읽지 않는 '죽은 설정'이었다. 느린 사이트를 위해
              값을 늘려도 아무 일도 일어나지 않았다(매직넘버 중복 + 표시=동작 불일치).
        건드리면: 설정 파일의 timeout 이 다시 장식용 숫자가 된다.
        """
        try:
            value = int(self.config.get("timeout", 30))
        except (TypeError, ValueError):
            value = 30
        # 너무 짧으면 정상 페이지도 실패하므로 하한을 둔다
        return max(value, MIN_PAGE_LOAD_TIMEOUT)

    def installed_chrome_major(self):
        """
        이 PC 에 설치된 크롬의 메이저 버전을 알아낸다 (못 찾으면 None).

        ⛔ 수정금지(DO NOT MODIFY — INTENDED)
        무엇: 설치 폴더의 버전 폴더명에서 버전을 읽는다.
        왜:   undetected_chromedriver 는 크롬 버전을 스스로 감지하지 못할 때가 있어
              "could not detect version_main ... assuming it is chrome 108 or higher" 로 넘어간 뒤
              엉뚱한 드라이버를 받아 실패한다. 그러면 ChromeDriverManager 폴백으로 다시 받는데
              여기서 매 실행마다 약 6초가 낭비됐다(실측: 00:32:43 → 00:32:49).
              실제 버전을 미리 알려주면 첫 시도에 성공한다.
        건드리면: 크롬을 켤 때마다 불필요한 재시도와 드라이버 재다운로드가 발생한다.
        """
        candidates = [
            r"C:\Program Files\Google\Chrome\Application",
            r"C:\Program Files (x86)\Google\Chrome\Application",
            os.path.join(os.environ.get("LOCALAPPDATA", ""), r"Google\Chrome\Application"),
        ]
        for base in candidates:
            try:
                if not base or not os.path.isdir(base):
                    continue
                versions = [n for n in os.listdir(base) if re.fullmatch(r"\d+\.\d+\.\d+\.\d+", n)]
                if versions:
                    newest = sorted(versions, key=lambda v: [int(x) for x in v.split('.')])[-1]
                    return int(newest.split('.')[0])
            except Exception:
                continue
        return None

    def build_user_agent(self, chrome_major=None):
        """
        브라우저에 씌울 User-Agent 문자열을 만든다. 만들 수 없으면 None(덮어쓰지 않음).

        ⛔ 수정금지(DO NOT MODIFY / DO NOT REPLACE WITH fake_useragent — INTENDED)
        무엇: '실제로 설치된 크롬 버전' 을 그대로 담은 Chrome UA 를 만든다.
        왜:   예전에는 fake_useragent 로 무작위 UA 를 받아 썼는데, 실측 결과 심각했다.
              · browsers=['chrome'] 로 요청했는데 20회 모두 **Edge** UA 를 돌려줬다
              · 매 호출이 내부적으로 실패해 고정된 fallback 하나만 계속 썼다(=로테이션 아님)
              · 그 UA 는 Chrome 122 인데 이 PC 의 실제 크롬은 151 이었다
              결과적으로 '크롬 151 엔진으로 접속하면서 나는 Edge 122 다' 라고 주장하는 꼴이 되어,
              봇 감지 시스템이 가장 쉽게 잡아내는 모순 신호를 스스로 만들어 보냈다.
              (계정 정지·IP 차단을 막는 것이 이 프로그램의 핵심 가치인데 정반대로 동작했다)
        참고:  UA 를 아예 덮어쓰지 않으면 headless 모드에서 'HeadlessChrome/151' 이 노출된다
              (실측 확인). 그래서 '덮어쓰지 않기' 도 답이 아니고, 실제 버전과 일치하는
              Chrome UA 로 덮어쓰는 것이 정답이다. 버전·플랫폼·엔진이 모두 실제와 맞고
              headless 흔적만 사라진다.
        건드리면: 봇으로 감지되어 차단되는 사이트가 늘어난다.
        """
        major = chrome_major or self.installed_chrome_major()
        if not major:
            return None
        return (
            f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            f"(KHTML, like Gecko) Chrome/{major}.0.0.0 Safari/537.36"
        )

    def setup_driver(self):
        """Initializes undetected-chromedriver."""

        # 실제 크롬 버전을 미리 알아둔다 (UA 생성과 드라이버 버전 지정에 함께 쓴다)
        chrome_major = self.installed_chrome_major()
        if chrome_major:
            self.logger.info(f"Detected installed Chrome major version: {chrome_major}")
        else:
            self.logger.warning("설치된 크롬 버전을 확인하지 못했습니다 (자동 감지에 맡깁니다).")

        def create_options():
            options = uc.ChromeOptions()

            # Headless mode
            # ⛔ 수정금지(DO NOT MODIFY — INTENDED): 수동 로그인과 화면 숨기기는 동시에 성립할 수 없다.
            # 왜: 화면이 없으면 사용자가 로그인할 수 없는데, 프로그램은 로그인 대기 시간만 흘려보내고
            #     비로그인 상태로 수집해 회원 전용 이미지를 전부 403 으로 실패시켰다.
            #     UI 에서도 안내하지만, settings.json 을 직접 고치면 이 충돌 상태로 실행할 수 있다.
            #     따라서 '실제로 브라우저를 만드는 이 지점'에서 최종적으로 막는다.
            if self.config.get("manual_login", False):
                if self.config.get("headless", True):
                    self.logger.warning(
                        "manual_login 이 켜져 있어 headless 를 무시합니다 "
                        "(화면이 보이지 않으면 로그인을 할 수 없습니다)."
                    )
            elif self.config.get("headless", True):
                options.add_argument("--headless=new")

            # User-Agent — 실제 설치된 크롬 버전과 일치하는 값을 쓴다 (build_user_agent 주석 참조)
            # ⛔ 수정금지(DO NOT MODIFY — INTENDED): 설정값(user_agent_rotation)을 실제로 확인한다.
            #    예전에는 이 설정을 아무도 읽지 않아, settings.json 에서 false 로 바꿔도
            #    User-Agent 가 계속 덮어써졌다('죽은 설정' — 표시와 동작 불일치).
            if self.config.get("user_agent_rotation", True):
                user_agent = self.build_user_agent(chrome_major)
                if user_agent:
                    self.logger.info(f"Using User-Agent: {user_agent}")
                    # ⛔ 수정금지(DO NOT REMOVE THE LEADING DASHES — INTENDED)
                    # 무엇: 반드시 '--user-agent=' 로 두 개의 하이픈을 붙인다.
                    # 왜:   예전 코드는 'user-agent=...' (하이픈 없음)였다. 크롬은 이것을 스위치로
                    #       인식하지 못하므로 **UA 덮어쓰기가 한 번도 동작하지 않았다.**
                    #       그런데 로그에는 "Using User-Agent: ..." 가 찍혀서, 적용된 것처럼 보였다.
                    #       실제로 브라우저가 보낸 UA 는 'HeadlessChrome/151...' 이었고(실측 확인),
                    #       이는 자동화 도구임을 그대로 알리는 가장 강한 봇 감지 신호다.
                    options.add_argument(f"--user-agent={user_agent}")
                else:
                    # 크롬 버전을 못 알아낸 경우 — 억지로 만든 UA 로 덮어쓰면 오히려 불일치가 되므로
                    # 브라우저 기본값을 그대로 둔다(headless 흔적이 남지만 모순 신호는 없다).
                    self.logger.warning(
                        "크롬 버전을 확인하지 못해 User-Agent 를 덮어쓰지 않습니다 (브라우저 기본값 사용)."
                    )
            else:
                self.logger.info("User-Agent rotation disabled by settings.")

            # Performance/Stealth
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("--start-maximized")
            options.add_argument("--disable-popup-blocking")
            options.add_argument("--disable-notifications")
            return options

        try:
            self.logger.info("Initializing undetected-chromedriver...")
            # Use undetected_chromedriver without needing standard webdriver_manager explicitly
            options = create_options()
            # ⛔ 수정금지(DO NOT MODIFY — INTENDED): version_main 에 실제 크롬 메이저 버전을 넘긴다.
            # 왜: 넘기지 않으면 undetected_chromedriver 가 버전을 감지하지 못해 엉뚱한 드라이버를
            #     받고 실패한 뒤 ChromeDriverManager 폴백으로 다시 받는다. 실측으로 매 실행 약 6초가
            #     낭비됐다(크롬 151 인데 122 로 가정 → 불일치 → 재다운로드).
            # 건드리면: 프로그램을 켤 때마다 불필요한 대기와 드라이버 재다운로드가 발생한다.
            self.driver = uc.Chrome(options=options, use_subprocess=True, version_main=chrome_major)
            self.driver.set_page_load_timeout(self._page_load_timeout())
            self.logger.info("WebDriver initialized successfully.")
        except Exception as e:
            error_msg = str(e)
            if "This version of ChromeDriver only supports Chrome version" in error_msg:
                self.logger.warning("ChromeDriver version mismatch detected. Attempting auto-recovery with ChromeDriverManager...")
                try:
                    # Automatically download the matching driver version for current chrome browser
                    from webdriver_manager.chrome import ChromeDriverManager
                    driver_path = ChromeDriverManager().install()

                    self.logger.info(f"Matched driver downloaded to: {driver_path}. Re-initializing uc.Chrome...")
                    # MUST recreate options because uc.Chrome mutates/destroys them on failure
                    fallback_options = create_options()
                    self.driver = uc.Chrome(
                        options=fallback_options, use_subprocess=True,
                        driver_executable_path=driver_path, version_main=chrome_major
                    )

                    self.driver.set_page_load_timeout(self._page_load_timeout())
                    self.logger.info("WebDriver initialized successfully via fallback driver manager.")
                except Exception as e2:
                    self.logger.error(f"Failed to initialize WebDriver even with forced version: {e2}\n{traceback.format_exc()}")
                    raise DriverSetupError(self._explain_driver_error(e2), e2)
            else:
                tb = traceback.format_exc()
                self.logger.error(f"Failed to initialize WebDriver: {e}\n{tb}")
                raise DriverSetupError(self._explain_driver_error(e), e)

    def _explain_driver_error(self, error):
        """
        크롬 관련 오류를 사용자가 이해할 수 있는 한국어 안내로 번역한다.
        (배포 후 문의가 가장 많이 몰리는 지점이라 원인별로 나눠서 안내)
        """
        msg = str(error).lower()

        if "cannot find chrome binary" in msg or "chrome not reachable" in msg or "no chrome binary" in msg:
            return ("크롬 브라우저를 찾을 수 없습니다.\n\n"
                    "1) 구글 크롬(Chrome)이 설치되어 있는지 확인해주세요. (https://www.google.com/chrome)\n"
                    "2) 이미 설치되어 있다면, 크롬을 한 번 실행했다가 종료한 뒤 다시 시도해주세요.")

        if "only supports chrome version" in msg or "session not created" in msg:
            return ("크롬 브라우저와 드라이버의 버전이 맞지 않습니다.\n\n"
                    "1) 크롬을 최신 버전으로 업데이트해주세요. (크롬 → 도움말 → Chrome 정보)\n"
                    "2) 업데이트 후 프로그램을 완전히 종료했다가 다시 실행해주세요.")

        if "permission" in msg or "access is denied" in msg or "winerror 5" in msg:
            return ("드라이버 파일을 저장할 권한이 없습니다.\n\n"
                    "1) 프로그램을 '관리자 권한으로 실행'해보세요.\n"
                    "2) 백신/보안 프로그램이 차단하고 있는지 확인해주세요.")

        if "timed out" in msg or "timeout" in msg or "connection" in msg or "urlopen" in msg:
            return ("드라이버를 내려받는 중 네트워크 연결에 실패했습니다.\n\n"
                    "1) 인터넷 연결 상태를 확인해주세요.\n"
                    "2) 회사/기관 네트워크라면 방화벽이 막고 있을 수 있습니다.")

        return ("크롬 드라이버를 준비하지 못했습니다.\n\n"
                "1) 크롬 브라우저 설치 및 최신 업데이트 여부를 확인해주세요.\n"
                "2) 실행 중인 크롬 창을 모두 닫고 다시 시도해주세요.\n"
                f"\n(상세 원인: {str(error)[:200]})")

    # ──────────────────────────────────────────────────────────
    # robots.txt 준수 (전역수칙 9: 플랫폼 규정 준수)
    # ──────────────────────────────────────────────────────────
    def is_allowed_by_robots(self, url):
        """
        robots.txt 가 이 주소의 수집을 허용하는지 확인한다.
        설정에서 꺼두면 항상 True. 조회 실패 시에도 True(과잉 차단 방지).
        """
        if not self.config.get("respect_robots", True):
            return True

        try:
            parsed = urlparse(url)
            base = f"{parsed.scheme}://{parsed.netloc}"

            if base not in self._robots_cache:
                rp = robotparser.RobotFileParser()
                rp.set_url(urljoin(base, "/robots.txt"))
                try:
                    rp.read()
                except Exception:
                    rp = None  # robots.txt 없음/조회 실패 → 제한 없음으로 간주
                self._robots_cache[base] = rp

            rp = self._robots_cache[base]
            if rp is None:
                return True
            return rp.can_fetch("*", url)
        except Exception:
            return True

    # ──────────────────────────────────────────────────────────
    # 크롤링 오케스트레이터
    # ──────────────────────────────────────────────────────────
    def crawl(self, start_url, target_selector=None, max_depth=1, progress_callback=None, stop_event=None):
        """
        Orchestrator for recursive crawling.
        """
        if not self.driver:
            self.setup_driver()

        # robots.txt 사전 확인 (시작 주소부터 막혀 있으면 아예 진행하지 않는다)
        if not self.is_allowed_by_robots(start_url):
            self.logger.warning(f"robots.txt disallows crawling: {start_url}")
            self.close()
            raise PermissionError(
                "이 사이트의 robots.txt 정책이 자동 수집을 허용하지 않습니다.\n\n"
                "• 사이트 운영자의 수집 거부 의사이므로 기본적으로는 존중해야 합니다.\n"
                "• 본인이 권한을 가진 사이트이거나 수집 허가를 받은 경우에만,\n"
                "  [일반 설정] 탭의 'robots.txt 정책 준수' 체크를 해제하고 다시 시도해주세요.\n"
                "  (해제 시 발생하는 모든 책임은 사용자 본인에게 있습니다.)"
            )

        # Handle Manual Login Pause once at the start of the crawl session
        if self.config.get("manual_login", False):
            if progress_callback: progress_callback("수동 로그인 대기 중... (브라우저에서 직접 로그인하세요)")
            self.logger.info("Manual login wait triggered. Please login now.")
            self.driver.get(start_url)
            wait_time = self.config.get("login_wait", 30)
            for i in range(wait_time, 0, -1):
                if stop_event and stop_event.is_set():
                    return []
                time.sleep(1)
                if i % 5 == 0 and progress_callback:
                    progress_callback(f"수동 로그인 대기 중... ({i}초 남음)")
            if progress_callback: progress_callback("로그인 대기 완료. 데이터 수집을 시작합니다.")

        visited_urls = set()
        # ⛔ 실제로 '불러온 페이지 수'를 센다. 링크 순회(깊이)와 페이지네이션 순회가
        #    같은 예산을 나눠 쓰게 해야, 둘을 동시에 켰을 때 곱셈으로 폭주하지 않는다.
        #    (예: 링크 100개 × 페이지네이션 30페이지 = 3,000회 요청)
        self._pages_loaded = 0
        queue = [(self.normalize_link(start_url), 1)]  # (url, current_depth)
        all_images = []
        seen_image_keys = set()  # 페이지 간(전역) 중복 제거용

        base_domain = urlparse(start_url).netloc

        try:
            while queue:
                if stop_event and stop_event.is_set():
                    self.logger.info("Crawl loop stopped by user.")
                    break

                # ⛔ 방문 상한 확인 (깊이 2단계 폭주 방지 — MAX_PAGES_PER_CRAWL 주석 참조)
                if self._pages_loaded >= MAX_PAGES_PER_CRAWL:
                    self.logger.warning(
                        f"Reached page limit ({MAX_PAGES_PER_CRAWL}). Stopping to avoid overloading the site."
                    )
                    if progress_callback:
                        progress_callback(
                            f"⚠️ 방문 페이지 상한({MAX_PAGES_PER_CRAWL}개)에 도달해 수집을 마칩니다.\n"
                            f"   → 대상 사이트에 과도한 부하를 주지 않기 위한 안전장치입니다.\n"
                            f"   → 더 모으려면 시작 주소를 나눠서 여러 번 수집해주세요."
                        )
                    break

                current_url, current_depth = queue.pop(0)

                if current_url in visited_urls:
                    continue
                visited_urls.add(current_url)

                if not self.is_allowed_by_robots(current_url):
                    self.logger.info(f"Skipped by robots.txt: {current_url}")
                    continue

                if progress_callback:
                    progress_callback(f"이동 중: {current_url} (깊이 {current_depth}/{max_depth})")

                # Process the page
                images, found_links = self._process_page(current_url, target_selector, progress_callback, stop_event)

                # 전역 중복 제거: 서로 다른 페이지에 같은 이미지가 걸려도 한 번만 담는다
                for img in images:
                    key = self.dedup_key(img['src'])
                    if key in seen_image_keys:
                        continue
                    seen_image_keys.add(key)
                    all_images.append(img)

                # Queue next level links
                if current_depth < max_depth:
                    for link in found_links:
                        # Simple domain filter to prevent leaving the site
                        if urlparse(link).netloc == base_domain and link not in visited_urls:
                            queue.append((link, current_depth + 1))

            # 브라우저를 닫기 전에 세션 쿠키를 확보한다.
            # (수동 로그인으로 얻은 인증 정보를 이미지 다운로드에 그대로 넘기기 위함)
            self._capture_cookies()

            self.logger.info(f"Total images found: {len(all_images)} from {len(visited_urls)} pages.")
            return all_images

        except Exception as e:
            self.logger.error(f"Crawl orchestrator error: {e}")
            self._capture_cookies()
            return all_images
        finally:
            self.close()

    def _capture_cookies(self):
        """현재 브라우저 세션의 쿠키를 저장해 둔다 (다운로더에 전달용)."""
        try:
            if self.driver:
                self.session_cookies = self.driver.get_cookies() or []
                if self.session_cookies:
                    self.logger.info(f"Captured {len(self.session_cookies)} session cookies for download reuse.")
        except Exception as e:
            self.logger.debug(f"Failed to capture cookies: {e}")

    def get_session_cookies(self):
        """수집 중 확보한 브라우저 쿠키 목록을 반환한다."""
        return self.session_cookies

    # ──────────────────────────────────────────────────────────
    # 페이지 단위 처리
    # ──────────────────────────────────────────────────────────
    def _process_page(self, url, target_selector, progress_callback, stop_event=None):
        """
        Process a single page: Navigate -> (Scroll -> Extract) x N pages -> Extract Links
        페이지네이션이 켜져 있으면 '다음 페이지'를 누를 때마다 그 페이지를 즉시 파싱해 누적한다.
        Returns: (images_list, links_list)
        """
        images = []
        links = []
        try:
            self.logger.info(f"Navigating to {url}...")
            self.driver.get(url)

            if stop_event and stop_event.is_set(): return [], []

            # 페이지네이션 순회 (최대 페이지 수 제한으로 무한 루프 방지)
            max_pages = int(self.config.get("max_pagination_pages", 30)) if self.config.get("use_pagination") else 1
            page_index = 0

            while page_index < max_pages:
                # 전체 예산을 넘기면 페이지네이션도 멈춘다 (깊이 × 페이지네이션 곱셈 폭주 방지)
                if getattr(self, "_pages_loaded", 0) >= MAX_PAGES_PER_CRAWL:
                    self.logger.warning("Page budget exhausted — stopping pagination.")
                    break
                page_index += 1
                self._pages_loaded = getattr(self, "_pages_loaded", 0) + 1

                # Smart Auto-Scroll (지연로딩 유도)
                self.auto_scroll(progress_callback, stop_event)
                if stop_event and stop_event.is_set():
                    break

                # ⛔ 중요: '다음 페이지'로 넘어가기 **전에** 현재 페이지를 반드시 파싱해야 한다.
                # 예전 버전은 순회가 모두 끝난 뒤에 한 번만 파싱해서, 1~N-1 페이지의 이미지가 통째로 유실됐다.
                self.logger.info(f"Parsing page content... (page {page_index})")
                soup = BeautifulSoup(self.driver.page_source, 'html.parser')

                page_title = "Untitled"
                if soup.title and soup.title.string:
                    page_title = soup.title.string.strip()

                # 첫 페이지에서만 안내한다(페이지네이션마다 같은 경고를 반복하면 로그가 도배된다)
                search_area = self._resolve_search_area(
                    soup, target_selector, progress_callback if page_index == 1 else None
                )
                images.extend(self._extract_images(search_area, url, page_title))
                links.extend(self._extract_links(soup, url))

                # 다음 페이지 버튼 클릭 시도
                if not self._go_to_next_page(progress_callback, stop_event):
                    break
                if stop_event and stop_event.is_set():
                    break

            # 페이지 내부 중복 제거 (쿼리스트링 제외 기준)
            images = self._dedup_images(images)

            self.logger.info(f"Found {len(images)} images and {len(links)} links on {url}")
            return images, links

        except Exception as e:
            self.logger.error(f"Page processing failed: {e}")
            # 지금까지 모은 것이라도 반환한다 (전량 손실 방지)
            return self._dedup_images(images), links

    def _resolve_search_area(self, soup, target_selector, callback=None):
        """
        '특정 영역만 수집' 옵션이 켜진 경우 해당 영역만 반환한다.

        ⛔ 침묵 실패 금지: 선택자가 페이지에 없거나 문법이 틀렸을 때는 페이지 전체를 수집하게 되는데,
           사용자는 영역 제한이 걸린 줄 알고 있다. 그래서 로그 파일에만 남기지 않고
           화면 로그에도 반드시 알린다(무엇이 잘못됐는지 알아야 선택자를 고칠 수 있다).
        """
        if not target_selector:
            return soup
        self.logger.info(f"Scoping search to: {target_selector}")
        try:
            selected_area = soup.select_one(target_selector)
            if selected_area:
                self.logger.info("Target section found.")
                return selected_area
            self.logger.warning(f"Target selector '{target_selector}' not found. Searching entire page.")
            if callback:
                callback(f"⚠️ 지정한 영역 '{target_selector}' 을 페이지에서 찾지 못해 "
                         f"페이지 전체를 수집합니다. (선택자를 다시 확인해주세요)")
        except Exception as e:
            self.logger.error(f"Invalid CSS Selector syntax '{target_selector}': {e}. Searching entire page instead.")
            if callback:
                callback(f"⚠️ 영역 선택자 '{target_selector}' 의 문법이 올바르지 않아 "
                         f"페이지 전체를 수집합니다. (예: #content, .gallery-grid)")
        return soup

    def _go_to_next_page(self, callback=None, stop_event=None):
        """'다음 페이지' 버튼을 눌러 다음 목록으로 이동. 성공하면 True."""
        if not self.config.get("use_pagination"):
            return False
        selector = (self.config.get("pagination_selector") or "").strip()
        if not selector:
            # ⛔ 침묵 실패 금지: 옵션은 켰는데 선택자가 없으면 순회가 조용히 1페이지에서 끝난다.
            #    사용자는 '왜 다음 페이지를 안 넘어가지?' 하고 원인을 알 수 없었다.
            self.logger.warning("Pagination enabled but selector is empty — staying on the first page.")
            if callback:
                callback("⚠️ '다음 페이지' 자동 클릭이 켜져 있지만 CSS 선택자가 비어 있어 "
                         "첫 페이지만 수집합니다. ([접속 및 순회] 탭에서 선택자를 입력해주세요)")
            return False

        from selenium.webdriver.common.by import By
        try:
            btn = self.driver.find_element(By.CSS_SELECTOR, selector)
            if not (btn and btn.is_displayed() and btn.is_enabled()):
                return False

            delay_max = self.config.get("random_delay_max", 2.0)
            self.driver.execute_script("arguments[0].click();", btn)
            if callback:
                callback("다음 페이지(Pagination)로 이동 중...")
            # ⛔ 통째로 sleep 하지 않는다. 딜레이 5단계에서는 이 대기가 7초까지 늘어나,
            #    중지 버튼을 눌러도 그 시간만큼 계속 요청이 나갔다.
            return self._sleep_interruptible(delay_max * 2, stop_event)
        except Exception:
            self.logger.debug("Pagination button not found or not clickable.")
            return False

    # ──────────────────────────────────────────────────────────
    # 이미지/링크 추출
    # ──────────────────────────────────────────────────────────
    def _extract_images(self, search_area, url, page_title):
        """<img>, <source>, CSS 배경 이미지에서 수집 대상을 뽑아낸다."""
        images = []
        # <picture> 안의 <img> 를 이미 담은 경우, 같은 <picture> 의 <source> 는 건너뛴다.
        # (같은 사진을 webp/jpg 두 번 받는 중복을 막기 위함 — 아래 2) 참조)
        covered_pictures = set()

        # --- 1) 일반 <img> 태그 ---
        for img in search_area.find_all('img'):
            src = self.pick_image_src(img)
            if not src:
                continue

            abs_url = self.to_absolute(url, src)
            if not abs_url or self.is_excluded(abs_url):
                continue

            # Context Extraction First (to help with description)
            context_text = ""
            figure = img.find_parent('figure')
            if figure:
                figcaption = figure.find('figcaption')
                if figcaption:
                    context_text = figcaption.get_text(strip=True)

            if not context_text:
                parent = img.parent
                if parent and parent.name in ['a', 'div', 'span', 'p', 'li']:
                    parent_text = parent.get_text(strip=True)
                    if len(parent_text) > 1 and len(parent_text) < 100:
                        context_text = parent_text

            # Find Nearest Heading (h1-h6) for better context
            heading_text = ""
            nearest_heading = img.find_previous(['h1', 'h2', 'h3', 'h4', 'h5', 'h6'])
            if nearest_heading:
                heading_text = nearest_heading.get_text(strip=True)

            # Description priority
            description = img.get('alt', '').strip() or img.get('title', '').strip() or img.get('aria-label', '').strip() or context_text or "설명 없음"

            image_data = self._build_image_data(abs_url, description, context_text, heading_text, url, page_title)
            if self.has_include_keywords([image_data['description'], image_data['context'], image_data['heading']]):
                images.append(image_data)
                parent_picture = img.find_parent('picture')
                if parent_picture is not None:
                    covered_pictures.add(id(parent_picture))

        # --- 2) <picture><source> (Modern HTML) ---
        for src_tag in search_area.find_all('source'):
            # ⛔ 수정금지(DO NOT MODIFY — INTENDED): 같은 <picture> 를 두 번 담지 않는다.
            # 왜: <picture><source srcset="photo.webp"><img src="photo.jpg"></picture> 구조에서
            #     <img> 와 <source> 를 각각 수집하면 '같은 사진'을 webp/jpg 로 두 번 내려받는다.
            #     주소가 달라서 중복 제거에도 걸리지 않아, 결과 폴더에 동일한 사진이 2장씩 쌓였다.
            #     <img> 는 모든 브라우저가 쓰는 기본 경로이므로 그쪽을 남기고 여기서 건너뛴다.
            parent_picture = src_tag.find_parent('picture')
            if parent_picture is not None and id(parent_picture) in covered_pictures:
                continue

            srcset = src_tag.get('srcset') or src_tag.get('data-srcset')
            if not srcset:
                continue
            best = self.pick_from_srcset(srcset)
            if not best:
                continue
            abs_url = self.to_absolute(url, best)
            if not abs_url or self.is_excluded(abs_url):
                continue

            image_data = self._build_image_data(abs_url, '반응형 이미지 (Picture Source)', '', '', url, page_title)
            if self.has_include_keywords([image_data['description'], image_data['context'], image_data['heading']]):
                images.append(image_data)

        # --- 3) CSS Background Image (PRO Feature) ---
        elements_with_bg = search_area.find_all(style=lambda value: value and 'background-image' in value)
        for el in elements_with_bg:
            style = el.get('style', '')
            bg_urls = re.findall(r'url\([\'"]?(.*?)[\'"]?\)', style)
            for bg_url in bg_urls:
                abs_url = self.to_absolute(url, bg_url)
                if not abs_url or self.is_excluded(abs_url):
                    continue

                context_text = el.get_text(strip=True)[:100]
                description = '배경 이미지 (CSS Background) - ' + (context_text[:20] if context_text else '설명 없음')

                image_data = self._build_image_data(abs_url, description, context_text, '', url, page_title)
                if self.has_include_keywords([image_data['description'], image_data['context'], image_data['heading']]):
                    images.append(image_data)

        return images

    def _build_image_data(self, abs_url, description, context, heading, source_page, page_title):
        return {
            'src': abs_url,
            'filename': self.get_filename_from_url(abs_url),
            'description': description,
            'context': context,
            'heading': heading,
            'source_page': source_page,
            'page_title': page_title,
        }

    def _extract_links(self, soup, url):
        """다음 깊이로 넘길 링크를 정규화하여 반환한다."""
        links = []
        for a in soup.find_all('a', href=True):
            link = self.to_absolute(url, a['href'])
            if not link:
                continue
            normalized = self.normalize_link(link)
            if normalized:
                links.append(normalized)
        return links

    def _dedup_images(self, images):
        """쿼리스트링/프래그먼트를 제외한 주소 기준으로 중복 제거."""
        seen = set()
        unique = []
        for img in images:
            key = self.dedup_key(img['src'])
            if key in seen:
                continue
            seen.add(key)
            unique.append(img)
        return unique

    def dedup_key(self, url):
        """
        중복 판정용 키.

        ⛔ 수정금지(DO NOT MODIFY — INTENDED)
        무엇: 경로가 '이미지 파일 확장자'로 끝나면 쿼리스트링을 무시하고,
              그렇지 않으면(동적 이미지 주소) 쿼리스트링까지 포함해서 구분한다.
        왜:   예전에는 무조건 쿼리스트링을 버렸다. 그래서
              · /photo.jpg?w=300 과 /photo.jpg?w=600 → 같은 파일 → 중복 처리 (여기까진 의도대로)
              · /image.php?id=1 과 /image.php?id=2 → '서로 다른 이미지'인데 같은 키가 되어
                첫 장만 받고 나머지를 전부 버렸다. CDN·이미지 프록시·게시판처럼 쿼리로
                이미지를 구분하는 사이트에서는 수집 결과가 통째로 유실됐다.
        건드리면: 동적 이미지 주소를 쓰는 사이트에서 조용히 이미지를 놓친다(v1.0.16의 그 사고와 동일 계열).
        """
        if url.startswith('data:'):
            return url[:256]
        parsed = urlparse(url)
        base = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"

        path_lower = parsed.path.lower()
        if any(path_lower.endswith(ext) for ext in KNOWN_IMG_EXTS):
            # 정적 이미지 파일 — 쿼리는 크기·캐시 파라미터일 뿐이므로 같은 이미지로 본다
            return base
        # 동적 이미지 주소(예: /img.php?id=2) — 쿼리가 다르면 다른 이미지다
        return f"{base}?{parsed.query}" if parsed.query else base

    # ──────────────────────────────────────────────────────────
    # URL 유틸
    # ──────────────────────────────────────────────────────────
    def to_absolute(self, base_url, src):
        """상대주소를 절대주소로. data URI 는 그대로 반환."""
        if not src:
            return None
        src = src.strip()
        if src.startswith('data:'):
            return src if src.startswith('data:image/') else None
        if src.startswith('//'):
            base_scheme = urlparse(base_url).scheme or 'https'
            return f"{base_scheme}:{src}"
        try:
            return urljoin(base_url, src)
        except Exception:
            return None

    def normalize_link(self, link):
        """
        링크 정규화: #프래그먼트 제거 + http(s)만 허용 + 문서/이미지 파일 제외.
        (예전 버전은 #a, #b 같은 앵커를 전부 '다른 페이지'로 취급해
         같은 페이지를 수십 번 재방문하며 시간을 낭비했다)
        """
        if not link:
            return None
        try:
            clean = urldefrag(link)[0]
            parsed = urlparse(clean)

            if parsed.scheme not in ('http', 'https'):
                return None

            path_lower = parsed.path.lower()
            if any(path_lower.endswith(ext) for ext in NON_PAGE_EXTS):
                return None

            # 끝 슬래시 통일 (http://a.com 과 http://a.com/ 를 같은 페이지로 취급)
            path = parsed.path or '/'
            return urlunparse((parsed.scheme, parsed.netloc, path, parsed.params, parsed.query, ''))
        except Exception:
            return None

    def pick_from_srcset(self, srcset):
        """
        srcset("a.jpg 400w, b.jpg 800w") 중 가장 큰 이미지를 고른다.
        디스크립터가 없으면 첫 번째를 사용.
        """
        best_url, best_score = None, -1
        for part in srcset.split(','):
            part = part.strip()
            if not part:
                continue
            bits = part.split()
            candidate = bits[0]
            score = 0
            if len(bits) > 1:
                desc = bits[1].lower()
                try:
                    if desc.endswith('w'):
                        score = int(float(desc[:-1]))
                    elif desc.endswith('x'):
                        score = int(float(desc[:-1]) * 1000)
                except ValueError:
                    score = 0
            if score > best_score:
                best_url, best_score = candidate, score
        return best_url

    def is_placeholder(self, src):
        """1x1 투명 이미지 등 '가짜 src' 인지 판별."""
        if not src:
            return True
        low = src.strip().lower()
        # 아주 짧은 data URI 는 대개 1x1 투명 GIF/PNG 플레이스홀더
        if low.startswith('data:image/') and len(low) < 512:
            return True
        return any(hint in low for hint in PLACEHOLDER_HINTS)

    def pick_image_src(self, img_tag):
        """
        <img> 태그에서 '진짜' 이미지 주소를 고른다.
        지연로딩(lazy-load) 사이트는 src 에 플레이스홀더를 넣고
        data-src / srcset 에 실제 주소를 두기 때문에 반드시 함께 살펴야 한다.
        """
        candidates = []

        # 1) srcset 계열 (가장 큰 해상도 우선)
        for attr in ('srcset', 'data-srcset', 'data-lazy-srcset'):
            value = img_tag.get(attr)
            if value:
                best = self.pick_from_srcset(value)
                if best:
                    candidates.append(best)

        # 2) 지연로딩 속성들 + 마지막에 일반 src
        for attr in LAZY_SRC_ATTRS:
            value = img_tag.get(attr)
            if value and value.strip():
                candidates.append(value.strip())

        # 플레이스홀더가 아닌 첫 후보를 우선 채택
        for candidate in candidates:
            if not self.is_placeholder(candidate):
                return candidate

        # 전부 플레이스홀더처럼 보이면 첫 후보라도 반환 (오탐 대비)
        return candidates[0] if candidates else None

    def _max_scrolls(self):
        """
        한 페이지에서 최대 몇 번까지 스크롤할지.

        ⛔ 수정금지(DO NOT MODIFY — INTENDED): 설정값이 0 이하면 '자동'(기본 상한)으로 본다.
        무엇: settings.json 의 max_scrolls 를 실제로 사용하되, 0 은 '제한 없음(자동)' 으로 읽는다.
        왜:   ① 이 키는 오래전부터 설정 파일에 들어 있었지만 코드는 250 을 하드코딩해서
                 아무 효과가 없는 '죽은 설정' 이었다(timeout 과 같은 문제).
              ② 실제 사용자 설정 파일에는 max_scrolls 가 0 으로 들어 있었다. 이 값을 그대로
                 '0번 스크롤' 로 해석하면 지연로딩(lazy-load) 이미지가 통째로 유실된다.
                 그래서 0 이하는 반드시 '자동' 으로 해석해야 한다.
        건드리면: 옛 설정 파일을 쓰는 사용자의 수집 결과가 갑자기 텅 비게 된다.
        """
        try:
            value = int(self.config.get("max_scrolls", 0))
        except (TypeError, ValueError):
            value = 0
        if value <= 0:
            return DEFAULT_MAX_SCROLLS
        return value

    def _sleep_interruptible(self, seconds, stop_event=None, chunk=0.1):
        """
        중지 버튼에 반응하면서 기다린다. (계속 진행해도 되면 True, 중지되면 False)

        ⛔ 수정금지(DO NOT MODIFY — INTENDED)
        무엇: 긴 대기를 0.1초 단위로 쪼개고, 매 조각마다 중지 요청을 확인한다.
        왜:   딜레이는 계정 정지·IP 차단을 막는 안전장치라 없앨 수 없다(전역수칙 6).
              그래서 '기다리기'와 '중지에 반응하기'를 동시에 해야 한다.
              예전에는 이 로직이 한 곳에만 있고 다른 대기 지점은 통째로 sleep 해서,
              그 구간에서 중지 버튼이 먹지 않았다.
        건드리면: 중지를 눌러도 프로그램이 몇 초씩 계속 요청을 보낸다.
        """
        remaining = max(float(seconds), 0.0)
        while remaining > 0:
            if stop_event and stop_event.is_set():
                return False
            time.sleep(min(chunk, remaining))
            remaining -= chunk
        return not (stop_event and stop_event.is_set())

    def auto_scroll(self, callback=None, stop_event=None):
        """Scrolls down to trigger lazy loading."""
        # Determine delay from config
        delay_min = self.config.get("random_delay_min", 1.0)
        delay_max = self.config.get("random_delay_max", 2.0)

        max_scrolls = self._max_scrolls()
        scroll_count = 0

        while scroll_count < max_scrolls:
            scroll_count += 1
            if stop_event and stop_event.is_set():
                break

            # ⛔ 수정금지(DO NOT MOVE THIS BELOW THE BOTTOM-CHECK — INTENDED)
            # 무엇: 진행 안내를 '스크롤 직후, 대기 전' 에 한다. 루프 끝으로 내리면 안 된다.
            # 왜:  ① 매번 찍으면 긴 페이지에서 로그가 같은 줄 수백 개로 도배된다 → 간격을 둔다.
            #      ② 그런데 안내를 루프 '끝' 에 두면, 짧은 페이지는 바닥에 닿아 break 로 먼저
            #         빠져나가므로 한 줄도 출력되지 않는다. 실제로 그렇게 만들어 돌려보고 확인했다.
            #         실측(rememoryphoto.com)에서 '이동 중' 이후 11초 동안 화면에 아무 변화가 없어
            #         사용자는 프로그램이 멈춘 것으로 느꼈다(전역수칙 4 — 멈춘 듯 보이게 하지 말 것).
            #      그래서 첫 스크롤은 '대기하기 전에' 반드시 알린다.
            if callback and (scroll_count == 1 or scroll_count % SCROLL_LOG_INTERVAL == 0):
                callback(f"페이지를 내리며 이미지를 불러오는 중... ({scroll_count}번째)")

            # Scroll down iteratively instead of all at once to seem more human
            self.driver.execute_script("window.scrollBy(0, 800);")

            # Random delay for human-like behavior
            delay = random.uniform(delay_min, delay_max)
            if not self._sleep_interruptible(delay, stop_event):
                return

            # Check if reached bottom
            scroll_pos = self.driver.execute_script("return window.pageYOffset + window.innerHeight")
            new_height = self.driver.execute_script("return document.body.scrollHeight")

            if scroll_pos >= new_height - 100:
                # Give it one more generous wait at the bottom
                # ⛔ 통째로 sleep 하지 않는다. 위쪽 스크롤 대기와 '같은 방식'으로 잘게 나눠 자며
                #    중지 버튼에 즉시 반응해야 한다. (예전에는 이 한 줄에서만 중지가 먹지 않았다)
                if not self._sleep_interruptible(delay_max, stop_event):
                    return
                final_height = self.driver.execute_script("return document.body.scrollHeight")
                if final_height == new_height:
                    break

    # ──────────────────────────────────────────────────────────
    # 필터
    # ──────────────────────────────────────────────────────────
    def is_excluded(self, url):
        """Checks if URL contains excluded keywords or forbidden extensions."""

        # data URI 는 주소 문자열 자체가 이미지 내용이라 키워드 검사가 무의미하다.
        if url.startswith('data:image/'):
            if not self.config.get("ext_allow_base64", True):
                return True
            return False

        parsed = urlparse(url)

        # 1. Custom Exclusion Keywords
        # ⛔ 호스트명(netloc)은 검사 대상에서 제외한다.
        #    예: 'banner' 를 제외 키워드로 두면 bannershop.co.kr 사이트의
        #    이미지가 전부 걸러지는 사고가 났었다. 경로/쿼리에만 적용한다.
        keywords_str = self.config.get("exclude_keywords", "logo, icon, button, tracker, pixel, banner")
        keywords = [kw.strip().lower() for kw in keywords_str.split(',') if kw.strip()]
        target = f"{parsed.path}?{parsed.query}".lower()

        for kw in keywords:
            if kw in target:
                return True

        # 2. Extension Filtering (Whitelist approach)
        # ⛔ 목록은 config_manager.allowed_extensions() 한 곳에서만 만든다.
        #    다운로더도 같은 함수를 써서 '실제 파일 포맷'을 검사한다(표시=동작 일치).
        valid_exts = allowed_extensions(self.config)

        # ⛔ 수정금지(DO NOT MODIFY — INTENDED)
        # 무엇: valid_exts 가 비어 있어도(확장자 체크박스를 전부 해제) 화이트리스트 검사를 그대로 수행한다.
        # 왜:   예전에는 `if valid_exts:` 가드가 있어서, 체크박스를 다 끄면 검사 자체를 건너뛰고
        #       오히려 '모든 이미지를 수집'하는 정반대 동작이 됐다.
        #       화이트리스트 방식에서 '허용 목록이 비었다'는 것은 '아무것도 허용하지 않음'이 맞다.
        # 건드리면: 사용자가 확장자를 모두 해제했는데 원치 않는 파일이 전부 수집된다.
        path = parsed.path.lower()
        if any(path.endswith(ext) for ext in KNOWN_IMG_EXTS):
            if not any(path.endswith(ext) for ext in valid_exts):
                return True  # 허용 목록에 없는 확장자

        return False

    def has_include_keywords(self, text_elements):
        """Checks if any extracted text contains the 'Must Include' keywords from UI."""
        kws_str = self.config.get("include_keywords", "").strip()
        if not kws_str:
            return True # Feature unused, allow all

        kws = [kw.strip().lower() for kw in kws_str.split(',') if kw.strip()]
        if not kws:
            return True

        combined_text = " ".join([str(t) for t in text_elements if t]).lower()
        for kw in kws:
            if kw in combined_text:
                return True

        return False

    def get_filename_from_url(self, url):
        """
        URL에서 파일명을 추출하고, 로깅/저장 시 문제가 없도록 정제한다.
        확장자는 붙이지 않는다 — 실제 이미지 포맷은 다운로드 후 PIL이 판별해서 붙인다.
        (예전에는 무조건 .jpg 를 붙여 PNG가 .jpg로 저장되는 문제가 있었다)
        """
        # data URI 는 주소 안에 이미지 본문(수천 자)이 들어 있어서
        # basename() 을 쓰면 파일명이 수백 자가 되어 윈도우 경로 길이(260자)를 넘겨버린다.
        # → 짧은 고유 이름을 새로 만들어 준다.
        if url.startswith('data:'):
            # ⛔ 수정금지(DO NOT MODIFY — INTENDED): 파이썬 내장 hash() 를 쓰지 않는다.
            # 왜: 문자열 hash() 는 실행할 때마다 값이 바뀐다(해시 시드 무작위화).
            #     그래서 같은 이미지를 다시 수집하면 파일명이 매번 달라져, 결과를 비교하거나
            #     재현할 수 없었다. hashlib 은 언제 어디서 돌려도 같은 값을 준다.
            digest = hashlib.sha1(url[:1024].encode('utf-8', 'ignore')).hexdigest()
            return f"embed_{digest[:8]}"

        path = urlparse(url).path
        filename = os.path.basename(path)
        stem = os.path.splitext(filename)[0]

        # ⛔ 수정금지(INTENDED): 파일명에서 ASCII 외 문자를 제거한다.
        # 왜: 윈도우 콘솔(cp949) 로깅 시 latin-1/유니코드 인코딩 에러가 발생했었다.
        clean_stem = re.sub(r'[^a-zA-Z0-9_\-]', '', stem)

        # 너무 긴 이름은 윈도우 경로 한계(260자)를 넘기므로 잘라낸다.
        clean_stem = clean_stem[:60]

        # 전부 잘려나갔으면(예: 한글/아랍어 전용 파일명) 대체 이름 생성
        if not clean_stem:
            clean_stem = f"image_{int(time.time() * 1000) % 100000000:08d}"

        return clean_stem

    def close(self):
        if self.driver:
            try:
                self.driver.quit()
            except OSError as e:
                # ⛔ 수정금지(INTENDED): undetected_chromedriver 는 윈도우 종료 시
                # "[WinError 6] The handle is invalid" 를 자주 던진다. 정상 종료이므로 무시한다.
                self.logger.debug(f"Expected OSError during driver quit: {e}")
            except Exception as e:
                self.logger.warning(f"Error while quitting driver: {e}")
            finally:
                self.driver = None
