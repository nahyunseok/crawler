import customtkinter as ctk
from src.utils.logger import get_logger
from src.utils.config_manager import ConfigManager
import threading
import tkinter as tk
import os

class MainWindow(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.logger = get_logger()
        self.config_manager = ConfigManager()
        
        # Window Setup
        self.title("Gemini Image Crawler")
        self.geometry("900x700")
        
        # Grid Configuration
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=0) # Header/Input
        self.grid_rowconfigure(1, weight=1) # Main Content (Log/Results)
        
        self.create_widgets()
        
    def create_widgets(self):
        # --- Sidebar ---
        self.sidebar_frame = ctk.CTkFrame(self, width=200, corner_radius=0)
        self.sidebar_frame.grid(row=0, column=0, rowspan=4, sticky="nsew")
        self.sidebar_frame.grid_rowconfigure(4, weight=1)

        self.logo_label = ctk.CTkLabel(self.sidebar_frame, text="이미지 수집기", font=ctk.CTkFont(size=20, weight="bold"))
        self.logo_label.grid(row=0, column=0, padx=20, pady=(20, 10))
        
        self.status_label = ctk.CTkLabel(self.sidebar_frame, text="상태: 준비됨", text_color="gray")
        self.status_label.grid(row=1, column=0, padx=20, pady=10)

        # --- Main Input Area ---
        self.main_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.main_frame.grid(row=0, column=1, padx=20, pady=20, sticky="nsew")
        
        self.url_label = ctk.CTkLabel(self.main_frame, text="수집할 주소(URL):", font=ctk.CTkFont(size=14))
        self.url_label.grid(row=0, column=0, sticky="w", pady=(0, 5))
        
        self.url_entry = ctk.CTkEntry(self.main_frame, placeholder_text="https://example.com", width=500)
        self.url_entry.grid(row=1, column=0, sticky="ew", pady=(0, 20))
        
        # Action Buttons
        self.button_frame = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        self.button_frame.grid(row=2, column=0, sticky="ew")
        
        self.start_button = ctk.CTkButton(self.button_frame, text="수집 시작", command=self.start_crawling_thread)
        self.start_button.pack(side="left", padx=(0, 10))
        
        self.stop_button = ctk.CTkButton(self.button_frame, text="중지", fg_color="red", hover_color="darkred", state="disabled")
        self.stop_button.pack(side="left", padx=(0, 10))
        
        self.open_result_button = ctk.CTkButton(self.button_frame, text="결과 폴더 열기", fg_color="gray", command=self.open_results_folder)
        self.open_result_button.pack(side="left")
        
        # --- Settings Area ---
        self.settings_frame = ctk.CTkFrame(self.main_frame)
        self.settings_frame.grid(row=3, column=0, sticky="ew", pady=20)
        
        # Basic Settings
        self.settings_inner = ctk.CTkFrame(self.settings_frame, fg_color="transparent")
        self.settings_inner.pack(fill="x", padx=10, pady=5)

        self.headless_var = ctk.BooleanVar(value=self.config_manager.get("headless"))
        self.headless_check = ctk.CTkCheckBox(self.settings_inner, text="화면 숨기기 (빠름)", variable=self.headless_var, command=self.save_settings)
        self.headless_check.pack(side="left", padx=5)
        
        self.min_size_label = ctk.CTkLabel(self.settings_inner, text="최소 크기:")
        self.min_size_label.pack(side="left", padx=(15, 5))
        
        self.min_size_entry = ctk.CTkEntry(self.settings_inner, width=50)
        self.min_size_entry.insert(0, str(self.config_manager.get("min_width")))
        self.min_size_entry.pack(side="left")
        self.min_size_entry.bind("<FocusOut>", self.save_settings)

        # Scoping Settings
        self.scope_frame = ctk.CTkFrame(self.settings_frame, fg_color="transparent")
        self.scope_frame.pack(fill="x", padx=10, pady=(0, 10))
        
        self.scope_var = ctk.BooleanVar(value=False)
        self.scope_check = ctk.CTkCheckBox(self.scope_frame, text="특정 영역만 수집", variable=self.scope_var, command=self.toggle_scope_input)
        self.scope_check.pack(side="left", padx=5)
        
        self.scope_entry = ctk.CTkEntry(self.scope_frame, placeholder_text="예: #content 또는 .gallery-grid", width=300)
        # self.scope_entry.pack(side="left", padx=10) # Packed properly in toggle function

        # Depth Settings (PRO Feature)
        self.depth_frame = ctk.CTkFrame(self.settings_frame, fg_color="transparent")
        self.depth_frame.pack(fill="x", padx=10, pady=(0, 5))
        
        self.depth_label = ctk.CTkLabel(self.depth_frame, text="크롤링 깊이:")
        self.depth_label.pack(side="left", padx=(5, 10))
        
        self.depth_var = ctk.StringVar(value="1단계 (현재)")
        self.depth_segment = ctk.CTkSegmentedButton(self.depth_frame, values=["1단계 (현재)", "2단계 (링크)"], variable=self.depth_var)
        self.depth_segment.pack(side="left")

        # --- Log Console ---
        self.log_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.log_frame.grid(row=1, column=1, padx=20, pady=(0, 20), sticky="nsew")
        
        self.log_label = ctk.CTkLabel(self.log_frame, text="실시간 로그", font=ctk.CTkFont(size=12, weight="bold"))
        self.log_label.pack(anchor="w")
        
        self.log_textbox = ctk.CTkTextbox(self.log_frame, height=200)
        self.log_textbox.pack(fill="both", expand=True)
        self.log_textbox.configure(state="disabled") # Read-only
        
    def toggle_scope_input(self):
        if self.scope_var.get():
            self.scope_entry.pack(side="left", padx=10, fill="x", expand=True)
        else:
            self.scope_entry.pack_forget()

    def open_results_folder(self):
        try:
            results_dir = os.path.join(os.getcwd(), "results")
            os.makedirs(results_dir, exist_ok=True)
            os.startfile(results_dir)
        except Exception as e:
            self.logger.error(f"Failed to open folder: {e}")



    def append_log(self, message):
        self.log_textbox.configure(state="normal")
        self.log_textbox.insert("end", message + "\n")
        self.log_textbox.see("end")
        self.log_textbox.configure(state="disabled")

    def save_settings(self, event=None):
        try:
            self.config_manager.set("headless", self.headless_var.get())
            self.config_manager.set("min_width", int(self.min_size_entry.get()))
            self.logger.info("Settings updated.")
        except ValueError:
            self.logger.error("Invalid input for settings.")

    def start_crawling_thread(self):
        url = self.url_entry.get()
        if not url:
            self.append_log("Error: Please enter a URL.")
            return
            
        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.status_label.configure(text="상태: 수집 중...", text_color="green")
        
        # Logic to start crawling thread...
        self.append_log(f"Starting crawl for: {url}")
        
        # Simulating threaded task
        t = threading.Thread(target=self.run_crawler, daemon=True)
        t.start()
        
    def run_crawler(self):
        url = self.url_entry.get()
        if not url:
            return

        try:
            # 1. Initialize Engine
            self.after(0, lambda: self.append_log("크롤러 엔진 초기화 중..."))
            from src.core.crawler_engine import CrawlerEngine
            from src.core.image_downloader import ImageDownloader
            
            crawler = CrawlerEngine(self.config_manager)
            downloader = ImageDownloader(self.config_manager)
            
            # 2. Start Crawling
            self.after(0, lambda: self.append_log(f"수집 시작: {url}\n시간이 조금 걸릴 수 있습니다..."))
            
            # Define a progress callback to update UI from thread
            def progress_callback(msg):
                self.after(0, lambda: self.append_log(msg))
            
            # Get Scope Selector
            target_selector = self.scope_entry.get() if self.scope_var.get() else None
            
            # Get Depth
            depth_str = self.depth_var.get()
            max_depth = 2 if "2단계" in depth_str else 1
            
            if max_depth > 1:
                self.after(0, lambda: self.append_log(f"딥 크롤링 시작 (깊이: {max_depth}). 시간이 더 소요됩니다."))

            images = crawler.crawl(url, target_selector=target_selector, max_depth=max_depth, progress_callback=progress_callback)
            
            if not images:
                self.after(0, lambda: self.append_log("이미지를 찾을 수 없거나 수집에 실패했습니다."))
                self.after(0, lambda: self.finish_crawling())
                return

            self.after(0, lambda: self.append_log(f"크롤링 완료. 이미지 {len(images)}개를 발견했습니다."))
            
            # 3. Download Images
            self.after(0, lambda: self.append_log("이미지 다운로드 시작..."))
            save_dir = downloader.process_images(images, base_result_dir="results")
            
            if save_dir:
                self.after(0, lambda: self.append_log(f"완료! 저장 위치: {save_dir}"))
                self.after(0, lambda: self.show_success_dialog(save_dir))
            else:
                self.after(0, lambda: self.append_log("다운로드가 완료되었으나 저장된 파일이 없습니다 (필터 설정 확인)."))

        except Exception as e:
            self.logger.error(f"Critical error in thread: {e}")
            self.after(0, lambda: self.append_log(f"Error: {e}"))
        finally:
            self.after(0, lambda: self.finish_crawling())
            
    def finish_crawling(self):
        self.start_button.configure(state="normal")
        self.stop_button.configure(state="disabled")
        self.status_label.configure(text="상태: 준비됨", text_color="gray")
        self.append_log("--- 작업 종료 ---")

    def show_success_dialog(self, path):
        import subprocess
        # Open folder in Explorer
        try:
            os.startfile(path)
        except Exception:
            pass # Linux/Mac support can be added later
