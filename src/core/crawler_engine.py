import time
import os
import random
from urllib.parse import urljoin, urlparse
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup
from src.utils.logger import get_logger

class CrawlerEngine:
    def __init__(self, config_manager):
        self.logger = get_logger()
        self.config = config_manager
        self.driver = None

    def setup_driver(self):
        """Initializes the Selenium WebDriver with configured options."""
        options = Options()
        
        # Headless mode
        if self.config.get("headless", True):
            options.add_argument("--headless=new")
        
        # Anti-detection & Stealth
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--start-maximized")
        
        # Disable image loading if configured (speed optimization)
        # Note: We might need images loaded to check dimensions via JS, but for now let's assume we download source.
        # If we disable images, some lazy loaders might not trigger completely, so use with caution.
        # options.add_argument("--blink-settings=imagesEnabled=false") 

        try:
            self.logger.info("Installing/Updating ChromeDriver...")
            service = Service(ChromeDriverManager().install())
            self.driver = webdriver.Chrome(service=service, options=options)
            self.logger.info("WebDriver initialized successfully.")
        except Exception as e:
            self.logger.error(f"Failed to initialize WebDriver: {e}")
            raise

    def crawl(self, url, target_selector=None, progress_callback=None):
        """
        Crawls the given URL and extracts image data.
        Returns a list of dictionaries: {'src': url, 'alt': text, 'title': text, 'page_url': url}
        """
        if not self.driver:
            self.setup_driver()

        try:
            self.logger.info(f"Navigating to {url}...")
            self.driver.get(url)
            
            # Smart Auto-Scroll
            self.auto_scroll(progress_callback)
            
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
                selected_area = soup.select_one(target_selector)
                if selected_area:
                    search_area = selected_area
                    self.logger.info("Target section found.")
                else:
                    self.logger.warning(f"Target selector '{target_selector}' not found. Searching entire page.")
            
            images = []
            img_tags = search_area.find_all('img')
            
            for index, img in enumerate(img_tags):
                src = img.get('src') or img.get('data-src') or img.get('data-original')
                if not src:
                    continue
                
                # Convert to absolute URL
                abs_url = urljoin(url, src)
                
                # Check exclusion keywords
                if self.is_excluded(abs_url):
                    continue

                # Description priority: alt > title > aria-label > figcaption > parent_text
                alt_text = img.get('alt', '').strip()
                title_text = img.get('title', '').strip()
                aria_label = img.get('aria-label', '').strip()
                
                # Context Extraction
                context_text = ""
                
                # 1. Check figcaption
                figure = img.find_parent('figure')
                if figure:
                    figcaption = figure.find('figcaption')
                    if figcaption:
                        context_text = figcaption.get_text(strip=True)
                
                # 2. Check parent container text (div/a/span) if concise
                if not context_text:
                    parent = img.parent
                    if parent and parent.name in ['a', 'div', 'span', 'p', 'li']:
                        # Get text but exclude the image text logic if any
                        parent_text = parent.get_text(strip=True)
                        if len(parent_text) > 1 and len(parent_text) < 100: # Limit length to avoid grabbing full article
                            context_text = parent_text

                # Combine signals for best description
                description = alt_text
                if not description: description = title_text
                if not description: description = aria_label
                if not description: description = context_text
                
                if not description:
                    description = "설명 없음"

                image_data = {
                    'src': abs_url,
                    'filename': self.get_filename_from_url(abs_url),
                    'description': description,
                    'context': context_text, # Save context separately too
                    'source_page': url,
                    'page_title': page_title # Pass title for folder naming
                }
                images.append(image_data)
                
            self.logger.info(f"Found {len(images)} images.")
            return images

        except Exception as e:
            self.logger.error(f"Crawling failed: {e}")
            return []
        finally:
            self.close()

    def auto_scroll(self, callback=None):
        """Scrolls down to trigger lazy loading."""
        last_height = self.driver.execute_script("return document.body.scrollHeight")
        
        while True:
            # Scroll down to bottom
            self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            
            # Random delay for human-like behavior
            delay = random.uniform(self.config.get("random_delay_min", 1), self.config.get("random_delay_max", 2))
            time.sleep(delay)
            
            # Calculate new scroll height and compare with last scroll height
            new_height = self.driver.execute_script("return document.body.scrollHeight")
            if new_height == last_height:
                break
            last_height = new_height
            
            if callback:
                callback("Scrolling...")

    def is_excluded(self, url):
        """Checks if URL contains excluded keywords."""
        keywords = ['icon', 'logo', 'button', 'tracker', 'pixel'] # Basic list, can be expanded via config
        lower_url = url.lower()
        for kw in keywords:
            if kw in lower_url:
                return True
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
            self.driver.quit()
            self.driver = None
