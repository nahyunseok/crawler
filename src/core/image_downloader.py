import os
import time
import requests
import pandas as pd
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from PIL import Image
from io import BytesIO
from urllib.parse import urlparse
from src.utils.logger import get_logger

class ImageDownloader:
    def __init__(self, config_manager):
        self.logger = get_logger()
        self.config = config_manager
        
    def process_images(self, images_data, base_result_dir="results"):
        """Downloads images and saves metadata to Excel."""
        if not images_data:
            self.logger.warning("No images to process.")
            return

        # Prepare directory: results/[PageTitle]_[Hostname]_[Date]/
        first_img = images_data[0]
        first_source = first_img['source_page']
        page_title = first_img.get('page_title', 'Untitled')
        
        # Sanitize title for filesystem
        safe_title = "".join([c for c in page_title if c.isalnum() or c in (' ', '-', '_')]).strip()
        safe_title = safe_title[:30] # Limit length
        if not safe_title:
            safe_title = "Untitled"

        hostname = urlparse(first_source).netloc.replace('www.', '')
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # New Format: [Title]_[Domain]_[Time] e.g. "iPhone15Pro_apple.com_20240101..."
        folder_name = f"[{safe_title}]_{hostname}_{timestamp}"
        
        save_dir = os.path.join(base_result_dir, folder_name)
        img_save_dir = os.path.join(save_dir, "images")
        os.makedirs(img_save_dir, exist_ok=True)
        
        self.logger.info(f"Saving results to {save_dir}")
        self.logger.info(f"Starting parallel download for {len(images_data)} images...")
        
        downloaded_images = []
        
        # PRO Feature: Parallel Downloading (5 workers)
        with ThreadPoolExecutor(max_workers=5) as executor:
            future_to_img = {
                executor.submit(self._download_single_image, img, idx, img_save_dir): img 
                for idx, img in enumerate(images_data)
            }
            
            for future in as_completed(future_to_img):
                result = future.result()
                if result:
                    downloaded_images.append(result)
                
        # Generate Excel Report
        self.create_report(downloaded_images, save_dir)
        return save_dir

    def _download_single_image(self, img, idx, save_dir):
        """Downloads a single image with retry logic (PRO Feature)."""
        url = img['src']
        filename = f"{idx+1:03d}_{img['filename']}"
        filepath = os.path.join(save_dir, filename)
        
        # PRO Feature: Smart Retry with Exponential Backoff
        max_retries = 3
        
        for attempt in range(max_retries):
            try:
                # Mimic browser headers
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                    'Referer': img['source_page']
                }
                
                response = requests.get(url, headers=headers, stream=True, timeout=10)
                
                if response.status_code == 200:
                    image_content = response.content
                    image = Image.open(BytesIO(image_content))
                    
                    min_width = self.config.get("min_width", 0)
                    min_height = self.config.get("min_height", 0)
                    
                    if image.width < min_width or image.height < min_height:
                        self.logger.info(f"Skipped {filename}: Too small ({image.width}x{image.height})")
                        return None
                        
                    # Save image
                    with open(filepath, 'wb') as f:
                        f.write(image_content)
                    
                    # Save Text Data (.txt)
                    txt_filename = os.path.splitext(filename)[0] + ".txt"
                    txt_filepath = os.path.join(save_dir, txt_filename)
                    try:
                        with open(txt_filepath, "w", encoding="utf-8") as f:
                            f.write(f"파일이름: {filename}\n")
                            f.write(f"출처링크: {url}\n")
                            f.write(f"이미지설명: {img.get('description', '없음')}\n")
                            f.write(f"----------------------------------------\n")
                            f.write(f"[주변 텍스트 문맥]\n")
                            f.write(f"{img.get('context', '없음')}\n")
                    except Exception as e:
                        pass # Text save failure shouldn't stop flow

                    # Update metadata
                    img['saved_filename'] = filename
                    img['resolution'] = f"{image.width}x{image.height}"
                    self.logger.info(f"Downloaded: {filename}")
                    return img
                    
                else:
                    self.logger.warning(f"Failed {filename} (Attempt {attempt+1}/{max_retries}): Status {response.status_code}")
                    
            except Exception as e:
                self.logger.error(f"Error {filename} (Attempt {attempt+1}/{max_retries}): {e}")
            
            # Backoff before retry (1s, 2s, 4s...)
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
        
        return None

    def create_report(self, images_data, output_dir):
        """Creates an Excel report from value data."""
        if not images_data:
            return
            
        df = pd.DataFrame(images_data)
        
        # Select and Reorder columns
        # Select and Reorder columns
        columns = ['saved_filename', 'description', 'context', 'src', 'resolution', 'source_page']
        # Ensure columns exist even if empty
        for col in columns:
            if col not in df.columns:
                df[col] = ""
                
        df = df[columns]
        df.columns = ['파일명', '이미지 설명(종합)', '주변 텍스트(Context)', '다운로드 URL', '해상도', '출처 페이지']
        
        excel_path = os.path.join(output_dir, "checklist.xlsx")
        try:
            df.to_excel(excel_path, index=False)
            self.logger.info(f"Excel report saved: {excel_path}")
        except Exception as e:
            self.logger.error(f"Failed to save Excel report: {e}")
