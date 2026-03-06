import time
import os
import random
import traceback
from urllib.parse import urljoin, urlparse
import undetected_chromedriver as uc
from fake_useragent import UserAgent
from bs4 import BeautifulSoup
from src.utils.logger import get_logger

class CrawlerEngine:
    def __init__(self, config_manager):
        self.logger = get_logger()
        self.config = config_manager
        self.driver = None

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
                self.logger.warning("ChromeDriver version mismatch detected. Downloading specific version 145...")
                try:
                    # Manually download the matching driver for v145
                    from webdriver_manager.chrome import ChromeDriverManager
                    driver_path = ChromeDriverManager(driver_version="145.0.7632.117").install()
                    
                    self.logger.info(f"Driver downloaded to: {driver_path}. Initializing uc.Chrome...")
                    # MUST recreate options because uc.Chrome mutates/destroys them on failure
                    fallback_options = create_options()
                    self.driver = uc.Chrome(options=fallback_options, use_subprocess=True, driver_executable_path=driver_path)
                    
                    self.driver.set_page_load_timeout(30)
                    self.logger.info("WebDriver initialized successfully with forced version 145.")
                except Exception as e2:
                    self.logger.error(f"Failed to initialize WebDriver even with forced version: {e2}\n{traceback.format_exc()}")
                    raise e2
            else:
                self.logger.error(f"Failed to initialize WebDriver: {e}\n{traceback.format_exc()}")
                raise e

    def crawl(self, start_url, target_selector=None, max_depth=1, progress_callback=None, stop_event=None):
        """
        Orchestrator for recursive crawling.
        """
        if not self.driver:
            self.setup_driver()

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
        queue = [(start_url, 1)] # (url, current_depth)
        all_images = []
        
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
                
                if progress_callback:
                    progress_callback(f"이동 중: {current_url} (깊이 {current_depth}/{max_depth})")

                # Process the page
                images, found_links = self._process_page(current_url, target_selector, progress_callback, stop_event)
                all_images.extend(images)
                
                # Queue next level links
                if current_depth < max_depth:
                    for link in found_links:
                        # Simple domain filter to prevent leaving the site
                        if urlparse(link).netloc == base_domain and link not in visited_urls:
                            queue.append((link, current_depth + 1))
            
            self.logger.info(f"Total images found: {len(all_images)} from {len(visited_urls)} pages.")
            return all_images
            
        except Exception as e:
            self.logger.error(f"Crawl orchestrator error: {e}")
            return all_images
        finally:
            self.close()

    def _process_page(self, url, target_selector, progress_callback, stop_event=None):
        """
        Process a single page: Navigate -> Scroll -> Extract Images -> Extract Links
        Returns: (images_list, links_list)
        """
        try:
            self.logger.info(f"Navigating to {url}...")
            self.driver.get(url)
            
            if stop_event and stop_event.is_set(): return [], []

            # Smart Auto-Scroll
            self.auto_scroll(progress_callback, stop_event)
            
            if stop_event and stop_event.is_set(): return [], []
            
            # Parse Content
            self.logger.info("Parsing page content...")
            soup = BeautifulSoup(self.driver.page_source, 'html.parser')
            
            # Get Page Title for folder naming
            page_title = "Untitled"
            if soup.title and soup.title.string:
                page_title = soup.title.string.strip()
            
            # Target Specific Section if requested
            search_area = soup
            if target_selector:
                self.logger.info(f"Scoping search to: {target_selector}")
                try:
                    from bs4.element import SoupStrainer
                    selected_area = soup.select_one(target_selector)
                    if selected_area:
                        search_area = selected_area
                        self.logger.info("Target section found.")
                    else:
                        self.logger.warning(f"Target selector '{target_selector}' not found. Searching entire page.")
                except Exception as e:
                    self.logger.error(f"Invalid CSS Selector syntax '{target_selector}': {e}. Searching entire page instead.")
            
            # Extract Images
            images = []
            img_tags = search_area.find_all('img')
            
            for index, img in enumerate(img_tags):
                src = img.get('src') or img.get('data-src') or img.get('data-original')
                if not src:
                    continue
                
                # Convert to absolute URL
                abs_url = urljoin(url, src)
                
                if self.is_excluded(abs_url):
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

                image_data = {
                    'src': abs_url,
                    'filename': self.get_filename_from_url(abs_url),
                    'description': description,
                    'context': context_text,
                    'heading': heading_text,
                    'source_page': url,
                    'page_title': page_title
                }
                images.append(image_data)
                
            # --- Picture Source Extraction (Modern HTML) ---
            source_tags = search_area.find_all('source')
            for src_tag in source_tags:
                srcset = src_tag.get('srcset') or src_tag.get('data-srcset')
                if srcset:
                    # srcset can have multiple urls separated by comma, just take the first one or split
                    first_src = srcset.split(',')[0].strip().split(' ')[0]
                    abs_url = urljoin(url, first_src)
                    
                    if not self.is_excluded(abs_url):
                        image_data = {
                            'src': abs_url,
                            'filename': self.get_filename_from_url(abs_url),
                            'description': '반응형 이미지 (Picture Source)',
                            'context': '',
                            'heading': '',
                            'source_page': url,
                            'page_title': page_title
                        }
                        images.append(image_data)
                
            # --- CSS Background Image Extraction (PRO Feature) ---
            elements_with_bg = search_area.find_all(style=lambda value: value and 'background-image' in value)
            for el in elements_with_bg:
                style = el.get('style', '')
                import re
                bg_urls = re.findall(r'url\([\'"]?(.*?)[\'"]?\)', style)
                for bg_url in bg_urls:
                    abs_url = urljoin(url, bg_url)
                    if self.is_excluded(abs_url):
                        continue
                        
                    context_text = el.get_text(strip=True)[:100]
                    
                    image_data = {
                        'src': abs_url,
                        'filename': self.get_filename_from_url(abs_url),
                        'description': '배경 이미지 (CSS Background) - ' + (context_text[:20] if context_text else '설명 없음'),
                        'context': context_text,
                        'heading': '',
                        'source_page': url,
                        'page_title': page_title
                    }
                    images.append(image_data)
                    
            # Deduplicate by URL
            seen_urls = set()
            unique_images = []
            for img in images:
                if img['src'] not in seen_urls:
                    seen_urls.add(img['src'])
                    unique_images.append(img)
            images = unique_images
                
            # Extract Links for recursion
            links = []
            a_tags = soup.find_all('a', href=True)
            for a in a_tags:
                href = a['href']
                abs_link = urljoin(url, href)
                links.append(abs_link)
                
            self.logger.info(f"Found {len(images)} images and {len(links)} links on {url}")
            return images, links

        except Exception as e:
            self.logger.error(f"Page processing failed: {e}")
            return [], []

    def auto_scroll(self, callback=None, stop_event=None):
        """Scrolls down to trigger lazy loading."""
        last_height = self.driver.execute_script("return document.body.scrollHeight")
        
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
            chunks = int(delay * 10)
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
                
                # Check for pagination click
                if self.config.get("use_pagination"):
                    selector = self.config.get("pagination_selector")
                    if selector:
                        from selenium.webdriver.common.by import By
                        try:
                            btn = self.driver.find_element(By.CSS_SELECTOR, selector)
                            if btn and btn.is_displayed():
                                self.driver.execute_script("arguments[0].click();", btn)
                                time.sleep(delay_max * 2) # Wait for network load
                                if callback: callback("다음 페이지(Pagination)로 이동 중...")
                                continue # Keep scrolling the newly loaded content
                        except Exception as e:
                            self.logger.debug(f"Pagination button not found or not clickable.")
                            
                final_height = self.driver.execute_script("return document.body.scrollHeight")
                if final_height == new_height:
                    break
            
            if callback:
                callback("Scrolling... (로봇 방지 우회 진행 중)")

    def is_excluded(self, url):
        """Checks if URL contains excluded keywords or forbidden extensions."""
        
        # 1. Custom Exclusion Keywords
        keywords_str = self.config.get("exclude_keywords", "logo, icon, button, tracker, pixel, banner")
        keywords = [kw.strip().lower() for kw in keywords_str.split(',') if kw.strip()]
        lower_url = url.lower()
        
        for kw in keywords:
            if kw in lower_url:
                return True
                
        # 2. Extension Filtering (Whitelist approach)
        valid_exts = []
        if self.config.get("ext_jpg", True): valid_exts.extend(['.jpg', '.jpeg'])
        if self.config.get("ext_png", True): valid_exts.append('.png')
        if self.config.get("ext_webp", True): valid_exts.append('.webp')
        if self.config.get("ext_gif", False): valid_exts.append('.gif')
        
        if valid_exts:
            path = urlparse(url).path.lower()
            # If it has an explicit image extension, check against whitelist
            known_img_exts = ['.jpg', '.jpeg', '.png', '.webp', '.gif', '.svg', '.bmp']
            if any(path.endswith(ext) for ext in known_img_exts):
                if not any(path.endswith(ext) for ext in valid_exts):
                    return True # Excluded extension
                
        return False

    def get_filename_from_url(self, url):
        """Extracts filename from URL."""
        path = urlparse(url).path
        name = os.path.basename(path)
        if not name or '.' not in name:
            name = f"image_{int(time.time())}.jpg"
        return name

    def close(self):
        if self.driver:
            try:
                self.driver.quit()
            except Exception as e:
                self.logger.warning(f"Error while quitting driver: {e}")
            finally:
                self.driver = None
