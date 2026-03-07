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
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
from openpyxl.utils import get_column_letter

class ImageDownloader:
    def __init__(self, config_manager):
        self.logger = get_logger()
        self.config = config_manager
        
    def process_images(self, images_data, base_result_dir="results", progress_callback=None, stop_event=None):
        """Downloads images and saves metadata to Excel."""
        if not images_data:
            self.logger.warning("No images to process.")
            return

        import json
        history_path = os.path.join(base_result_dir, "download_history.json")
        history = set()
        if os.path.exists(history_path):
            try:
                with open(history_path, 'r', encoding='utf-8') as f:
                    history = set(json.load(f))
            except Exception:
                pass
                
        # Filter duplicates (Resume feature)
        new_images = []
        for img in images_data:
            if img['src'] in history:
                self.logger.info(f"Skipped {img['filename']}: Already downloaded (이어받기)")
                continue
            new_images.append(img)
            
        if not new_images:
            self.logger.info("모든 이미지가 이미 다운로드되어 있습니다. (이어받기 완료)")
            if progress_callback: progress_callback(1.0)
            return base_result_dir
            
        images_to_process = new_images

        # Prepare directory: results/[PageTitle]_[Hostname]_[Date]/
        first_img = images_data[0]
        first_source = first_img['source_page']
        page_title = first_img.get('page_title', 'Untitled')
        
        # Sanitize title for filesystem
        safe_title = "".join([c for c in page_title if c.isalnum() or c in (' ', '-', '_')]).strip()
        safe_title = safe_title[:30] # Limit length
        if not safe_title:
            safe_title = "Untitled"

        hostname = urlparse(first_source).netloc.replace('www.', '').replace(':', '_')
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # New Format: [Title]_[Domain]_[Time] e.g. "iPhone15Pro_apple.com_20240101..."
        folder_name = f"[{safe_title}]_{hostname}_{timestamp}"
        
        save_dir = os.path.join(base_result_dir, folder_name)
        img_save_dir = os.path.join(save_dir, "images")
        os.makedirs(img_save_dir, exist_ok=True)
        
        self.logger.info(f"Saving results to {save_dir}")
        self.logger.info(f"Starting parallel download for {len(images_data)} images...")
        
        downloaded_images = []
        total_images = len(images_to_process)
        completed = 0
        
        # PRO Feature: Parallel Downloading (5 workers)
        with ThreadPoolExecutor(max_workers=5) as executor:
            future_to_img = {
                executor.submit(self._download_single_image, img, idx, img_save_dir, stop_event): img 
                for idx, img in enumerate(images_to_process)
            }
            
            for future in as_completed(future_to_img):
                if stop_event and stop_event.is_set():
                    self.logger.info("Image downloading stopped by user.")
                    break
                completed += 1
                if progress_callback:
                    progress_callback(completed / total_images)
                    
                result = future.result()
                if result:
                    downloaded_images.append(result)
                    history.add(result['src'])
                    
        # Save History
        try:
            with open(history_path, 'w', encoding='utf-8') as f:
                json.dump(list(history), f, ensure_ascii=False, indent=2)
        except Exception as e:
            self.logger.warning(f"Failed to save download history: {e}")
                
        # Generate Excel Report
        self.create_report(downloaded_images, save_dir)
        return save_dir

    def _download_single_image(self, img, idx, save_dir, stop_event=None):
        """Downloads a single image with retry logic (PRO Feature)."""
        url = img['src']
        filename = f"{idx+1:03d}_{img['filename']}"
        filepath = os.path.join(save_dir, filename)
        
        # PRO Feature: Smart Retry with Exponential Backoff
        max_retries = 3
        
        for attempt in range(max_retries):
            if stop_event and stop_event.is_set():
                return None
                
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
                            f.write(f"단락 제목(Heading): {img.get('heading', '없음')}\n")
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
        columns = ['saved_filename', 'heading', 'description', 'context', 'src', 'resolution', 'source_page']
        for col in columns:
            if col not in df.columns:
                df[col] = ""
                
        # Add scrape time
        df['scrape_time'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        columns.append('scrape_time')
                
        df = df[columns]
        df.columns = [
            '수집된 파일명', 
            '소속 문단 제목 (주제 파악용)', 
            '이미지 자체 설명 (Alt/Title 등)', 
            '주변 텍스트 문맥 (본문 내용)', 
            '실제 다운로드 통로 URL', 
            '해상도', 
            '출처 페이지 사이트', 
            '수집 일시'
        ]
        
        excel_path = os.path.join(output_dir, "checklist.xlsx")
        try:
            # Save using Pandas
            with pd.ExcelWriter(excel_path, engine='openpyxl') as writer:
                df.to_excel(writer, index=False, sheet_name='수집 결과')
                
                # Format using openpyxl
                workbook = writer.book
                worksheet = writer.sheets['수집 결과']
                
                header_font = Font(bold=True, color="FFFFFF")
                header_fill = PatternFill(start_color="4F81BD", end_color="4F81BD", fill_type="solid")
                thin_border = Border(left=Side(style='thin'), right=Side(style='thin'), top=Side(style='thin'), bottom=Side(style='thin'))
                center_alignment = Alignment(horizontal="center", vertical="center")
                wrap_alignment = Alignment(wrap_text=True, vertical="center")
                
                # Format Headers
                for col_num, cell in enumerate(worksheet[1], 1):
                    cell.font = header_font
                    cell.fill = header_fill
                    cell.alignment = center_alignment
                    cell.border = thin_border
                    
                # Format Data Cells & Auto-width
                column_widths = {'A': 25, 'B': 35, 'C': 40, 'D': 50, 'E': 40, 'F': 15, 'G': 40, 'H': 20}
                for col_letter, width in column_widths.items():
                    worksheet.column_dimensions[col_letter].width = width
                    
                for row in worksheet.iter_rows(min_row=2):
                    for idx, cell in enumerate(row):
                        cell.border = thin_border
                        if idx in [1, 2, 3]: # Heading, Description and Context -> Wrap text
                            cell.alignment = wrap_alignment
                        else:
                            cell.alignment = Alignment(vertical="center")

            self.logger.info(f"Excel report saved: {excel_path}")
        except Exception as e:
            self.logger.error(f"Failed to save Excel report: {e}")
