import time
import os
import random
import re
import traceback
from urllib.parse import urljoin, urlparse, urldefrag, urlunparse
from urllib import robotparser
import undetected_chromedriver as uc
from fake_useragent import UserAgent
from bs4 import BeautifulSoup
from src.utils.logger import get_logger

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

# 링크 큐에 넣으면 안 되는 파일 확장자 (문서/압축/미디어 등)
NON_PAGE_EXTS = (
    '.pdf', '.zip', '.rar', '.7z', '.exe', '.dmg', '.hwp', '.doc', '.docx',
    '.xls', '.xlsx', '.ppt', '.pptx', '.mp3', '.mp4', '.avi', '.mov', '.mkv',
    '.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg', '.ico', '.css', '.js',
)

# 주소만 보고 '이미지 파일'로 판단할 수 있는 확장자 (화이트리스트 검사 대상)
KNOWN_IMG_EXTS = ('.jpg', '.jpeg', '.png', '.webp', '.gif', '.svg', '.bmp')

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
    def setup_driver(self):
        """Initializes undetected-chromedriver."""

        def create_options():
            options = uc.ChromeOptions()

            # Headless mode
            if self.config.get("headless", True):
                options.add_argument("--headless=new")

            # Dynamic User-Agent
            ua = UserAgent(os='windows', browsers=['chrome'])
            random_ua = ua.random
            self.logger.info(f"Using User-Agent: {random_ua}")
            options.add_argument(f"user-agent={random_ua}")

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
            self.driver = uc.Chrome(options=options, use_subprocess=True)
            self.driver.set_page_load_timeout(30)
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
                    self.driver = uc.Chrome(options=fallback_options, use_subprocess=True, driver_executable_path=driver_path)

                    self.driver.set_page_load_timeout(30)
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
        queue = [(self.normalize_link(start_url), 1)]  # (url, current_depth)
        all_images = []
        seen_image_keys = set()  # 페이지 간(전역) 중복 제거용

        base_domain = urlparse(start_url).netloc

        try:
            while queue:
                if stop_event and stop_event.is_set():
                    self.logger.info("Crawl loop stopped by user.")
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
                page_index += 1

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

                search_area = self._resolve_search_area(soup, target_selector)
                images.extend(self._extract_images(search_area, url, page_title))
                links.extend(self._extract_links(soup, url))

                # 다음 페이지 버튼 클릭 시도
                if not self._go_to_next_page(progress_callback):
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

    def _resolve_search_area(self, soup, target_selector):
        """'특정 영역만 수집' 옵션이 켜진 경우 해당 영역만 반환한다."""
        if not target_selector:
            return soup
        self.logger.info(f"Scoping search to: {target_selector}")
        try:
            selected_area = soup.select_one(target_selector)
            if selected_area:
                self.logger.info("Target section found.")
                return selected_area
            self.logger.warning(f"Target selector '{target_selector}' not found. Searching entire page.")
        except Exception as e:
            self.logger.error(f"Invalid CSS Selector syntax '{target_selector}': {e}. Searching entire page instead.")
        return soup

    def _go_to_next_page(self, callback=None):
        """'다음 페이지' 버튼을 눌러 다음 목록으로 이동. 성공하면 True."""
        if not self.config.get("use_pagination"):
            return False
        selector = (self.config.get("pagination_selector") or "").strip()
        if not selector:
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
            time.sleep(delay_max * 2)  # 네트워크 로딩 대기
            return True
        except Exception:
            self.logger.debug("Pagination button not found or not clickable.")
            return False

    # ──────────────────────────────────────────────────────────
    # 이미지/링크 추출
    # ──────────────────────────────────────────────────────────
    def _extract_images(self, search_area, url, page_title):
        """<img>, <source>, CSS 배경 이미지에서 수집 대상을 뽑아낸다."""
        images = []

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

        # --- 2) <picture><source> (Modern HTML) ---
        for src_tag in search_area.find_all('source'):
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
        """중복 판정용 키 (data URI 는 내용 앞부분으로 판정)."""
        if url.startswith('data:'):
            return url[:256]
        parsed = urlparse(url)
        return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"

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

    def auto_scroll(self, callback=None, stop_event=None):
        """Scrolls down to trigger lazy loading."""
        # Determine delay from config
        delay_min = self.config.get("random_delay_min", 1.0)
        delay_max = self.config.get("random_delay_max", 2.0)

        max_scrolls = 250 # Limit to prevent infinite scrolling on malicious pages
        scroll_count = 0

        while scroll_count < max_scrolls:
            scroll_count += 1
            if stop_event and stop_event.is_set():
                break

            # Scroll down iteratively instead of all at once to seem more human
            self.driver.execute_script("window.scrollBy(0, 800);")

            # Random delay for human-like behavior
            delay = random.uniform(delay_min, delay_max)
            # Sleep in small chunks to react to stop button faster
            chunks = max(int(delay * 10), 1)
            for _ in range(chunks):
                if stop_event and stop_event.is_set():
                    return
                time.sleep(0.1)

            # Check if reached bottom
            scroll_pos = self.driver.execute_script("return window.pageYOffset + window.innerHeight")
            new_height = self.driver.execute_script("return document.body.scrollHeight")

            if scroll_pos >= new_height - 100:
                # Give it one more generous wait at the bottom
                time.sleep(delay_max)
                final_height = self.driver.execute_script("return document.body.scrollHeight")
                if final_height == new_height:
                    break

            if callback:
                callback("Scrolling... (로봇 방지 우회 진행 중)")

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
        valid_exts = []
        if self.config.get("ext_jpg", True): valid_exts.extend(['.jpg', '.jpeg'])
        if self.config.get("ext_png", True): valid_exts.append('.png')
        if self.config.get("ext_webp", True): valid_exts.append('.webp')
        if self.config.get("ext_gif", False): valid_exts.append('.gif')

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
            return f"embed_{abs(hash(url[:1024])) % 100000000:08d}"

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
