import customtkinter as ctk
from src.utils.logger import get_logger
from src.utils.config_manager import ConfigManager
import threading
import tkinter as tk
import os

class MainWindow(ctk.CTk):
    def __init__(self, license_manager):
        super().__init__()

        self.logger = get_logger()
        self.config_manager = ConfigManager()
        self.license_manager = license_manager
        
        self.stop_event = threading.Event()
        
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

        self.logo_label = ctk.CTkLabel(self.sidebar_frame, text="Gemini\n이미지 수집기", font=ctk.CTkFont(size=24, weight="bold"))
        self.logo_label.grid(row=0, column=0, padx=20, pady=(30, 10))
        
        self.status_label = ctk.CTkLabel(self.sidebar_frame, text="상태: 준비됨", text_color="gray", font=ctk.CTkFont(size=14))
        self.status_label.grid(row=1, column=0, padx=20, pady=10)
        
        # License status
        is_valid, exp_str, days = self.license_manager.get_license_status()
        lic_text = f"라이센스: {days}일 남음\n({exp_str.split(' ')[0]})" if is_valid else "라이센스: 미인증"
        self.license_label = ctk.CTkLabel(self.sidebar_frame, text=lic_text, font=ctk.CTkFont(size=11), text_color="lightgray")
        self.license_label.grid(row=2, column=0, padx=20, pady=(20, 5))
        
        self.renew_btn = ctk.CTkButton(self.sidebar_frame, text="라이센스 갱신 / 연장", font=ctk.CTkFont(size=12), fg_color="transparent", border_width=1, command=self.show_license_window)
        self.renew_btn.grid(row=3, column=0, padx=20, pady=5)

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
        
        self.start_button = ctk.CTkButton(self.button_frame, text="🚀 수집 시작", font=ctk.CTkFont(size=15, weight="bold"), height=40, command=self.start_crawling_thread)
        self.start_button.pack(side="left", padx=(0, 10))
        
        self.stop_button = ctk.CTkButton(self.button_frame, text="🛑 중지", font=ctk.CTkFont(size=15, weight="bold"), height=40, fg_color="red", hover_color="darkred", state="disabled", command=self.stop_crawling)
        self.stop_button.pack(side="left", padx=(0, 10))
        
        self.open_result_button = ctk.CTkButton(self.button_frame, text="📁 결과 폴더 열기", font=ctk.CTkFont(size=15), height=40, fg_color="gray", command=self.open_results_folder)
        self.open_result_button.pack(side="left")
        
        # --- Settings Area (Tabs) ---
        self.settings_tabs = ctk.CTkTabview(self.main_frame, height=180)
        self.settings_tabs.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        
        tab_basic = self.settings_tabs.add("일반 설정")
        tab_filter = self.settings_tabs.add("필터 및 고급")
        tab_auth = self.settings_tabs.add("계정 및 접속")

        # --- Tab 1: Basic ---
        self.settings_inner = ctk.CTkFrame(tab_basic, fg_color="transparent")
        self.settings_inner.pack(fill="x", padx=5, pady=5)

        self.headless_var = ctk.BooleanVar(value=self.config_manager.get("headless"))
        self.headless_check = ctk.CTkCheckBox(self.settings_inner, text="화면 숨기기 (빠름/추적위험)", variable=self.headless_var, command=self.save_settings)
        self.headless_check.pack(side="left", padx=5)
        
        self.delay_label = ctk.CTkLabel(self.settings_inner, text="안전 딜레이(Bot방지):")
        self.delay_label.pack(side="left", padx=(15, 5))
        self.delay_slider = ctk.CTkSlider(self.settings_inner, from_=1, to=5, number_of_steps=4, width=100, command=self.save_settings_event)
        self.delay_slider.set(self.config_manager.get("delay_level", 2))
        self.delay_slider.pack(side="left", padx=5)

        self.scope_frame = ctk.CTkFrame(tab_basic, fg_color="transparent")
        self.scope_frame.pack(fill="x", padx=5, pady=5)
        
        self.scope_var = ctk.BooleanVar(value=False)
        self.scope_check = ctk.CTkCheckBox(self.scope_frame, text="특정 영역만 수집", variable=self.scope_var, command=self.toggle_scope_input)
        self.scope_check.pack(side="left", padx=5)
        self.scope_entry = ctk.CTkEntry(self.scope_frame, placeholder_text="예: #content 또는 .gallery-grid", width=250)
        
        self.depth_label = ctk.CTkLabel(self.scope_frame, text="크롤링 깊이(PRO):")
        self.depth_label.pack(side="left", padx=(20, 5))
        self.depth_var = ctk.StringVar(value="1단계 (현재)")
        self.depth_segment = ctk.CTkSegmentedButton(self.scope_frame, values=["1단계 (현재)", "2단계 (링크)"], variable=self.depth_var)
        self.depth_segment.pack(side="left")

        # --- Tab 2: Filters ---
        self.filter_row1 = ctk.CTkFrame(tab_filter, fg_color="transparent")
        self.filter_row1.pack(fill="x", padx=5, pady=5)
        
        self.min_size_label = ctk.CTkLabel(self.filter_row1, text="최소 오차 크기(px):")
        self.min_size_label.pack(side="left", padx=(5, 5))
        self.min_size_entry = ctk.CTkEntry(self.filter_row1, width=60)
        self.min_size_entry.insert(0, str(self.config_manager.get("min_width", 200)))
        self.min_size_entry.pack(side="left")
        self.min_size_entry.bind("<FocusOut>", self.save_settings)
        
        self.ext_label = ctk.CTkLabel(self.filter_row1, text="허용 확장자:")
        self.ext_label.pack(side="left", padx=(20, 5))
        
        self.ext_jpg = ctk.BooleanVar(value=self.config_manager.get("ext_jpg", True))
        self.ext_png = ctk.BooleanVar(value=self.config_manager.get("ext_png", True))
        self.ext_webp = ctk.BooleanVar(value=self.config_manager.get("ext_webp", True))
        self.ext_gif = ctk.BooleanVar(value=self.config_manager.get("ext_gif", False))
        
        ctk.CTkCheckBox(self.filter_row1, text="JPG", variable=self.ext_jpg, width=50, command=self.save_settings).pack(side="left", padx=2)
        ctk.CTkCheckBox(self.filter_row1, text="PNG", variable=self.ext_png, width=50, command=self.save_settings).pack(side="left", padx=2)
        ctk.CTkCheckBox(self.filter_row1, text="WEBP", variable=self.ext_webp, width=50, command=self.save_settings).pack(side="left", padx=2)
        ctk.CTkCheckBox(self.filter_row1, text="GIF", variable=self.ext_gif, width=50, command=self.save_settings).pack(side="left", padx=2)
        
        self.filter_row2 = ctk.CTkFrame(tab_filter, fg_color="transparent")
        self.filter_row2.pack(fill="x", padx=5, pady=5)
        
        self.exclude_label = ctk.CTkLabel(self.filter_row2, text="제외 키워드:")
        self.exclude_label.pack(side="left", padx=5)
        self.exclude_entry = ctk.CTkEntry(self.filter_row2, placeholder_text="logo, icon, banner, ad", width=350)
        self.exclude_entry.insert(0, self.config_manager.get("exclude_keywords", "logo, icon, button, tracker, pixel, banner"))
        self.exclude_entry.pack(side="left", padx=5)
        self.exclude_entry.bind("<FocusOut>", self.save_settings)

        # --- Tab 3: Auth & Paging ---
        self.auth_row1 = ctk.CTkFrame(tab_auth, fg_color="transparent")
        self.auth_row1.pack(fill="x", padx=5, pady=5)
        
        self.login_var = ctk.BooleanVar(value=self.config_manager.get("manual_login", False))
        self.login_check = ctk.CTkCheckBox(self.auth_row1, text="수동 로그인 대기 활성화", variable=self.login_var, command=self.save_settings)
        self.login_check.pack(side="left", padx=5)
        
        self.login_wait_label = ctk.CTkLabel(self.auth_row1, text="대기 시간(초):")
        self.login_wait_label.pack(side="left", padx=(20, 5))
        self.login_wait_entry = ctk.CTkEntry(self.auth_row1, width=50)
        self.login_wait_entry.insert(0, str(self.config_manager.get("login_wait", 30)))
        self.login_wait_entry.pack(side="left")
        self.login_wait_entry.bind("<FocusOut>", self.save_settings)

        self.auth_row2 = ctk.CTkFrame(tab_auth, fg_color="transparent")
        self.auth_row2.pack(fill="x", padx=5, pady=5)

        self.paging_var = ctk.BooleanVar(value=self.config_manager.get("use_pagination", False))
        self.paging_check = ctk.CTkCheckBox(self.auth_row2, text="'다음 페이지' 버튼 자동 클릭 (순회수집)", variable=self.paging_var, command=self.save_settings)
        self.paging_check.pack(side="left", padx=5)
        
        self.paging_entry = ctk.CTkEntry(self.auth_row2, placeholder_text="CSS 선택자 (예: a.next, #btnNext)", width=200)
        self.paging_entry.insert(0, self.config_manager.get("pagination_selector", ""))
        self.paging_entry.pack(side="left", padx=5)
        self.paging_entry.bind("<FocusOut>", self.save_settings)

        # --- Progress Bar & Log ---
        self.log_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.log_frame.grid(row=1, column=1, padx=20, pady=(0, 20), sticky="nsew")
        
        self.progress_bar = ctk.CTkProgressBar(self.log_frame)
        self.progress_bar.pack(fill="x", pady=(0, 10))
        self.progress_bar.set(0)
        
        self.log_label = ctk.CTkLabel(self.log_frame, text="실시간 로그", font=ctk.CTkFont(size=12, weight="bold"))
        self.log_label.pack(anchor="w")
        
        self.log_textbox = ctk.CTkTextbox(self.log_frame, height=200, font=ctk.CTkFont(family="Consolas", size=12))
        self.log_textbox.pack(fill="both", expand=True)
        self.log_textbox.configure(state="disabled") # Read-only
        
    def show_license_window(self):
        from src.ui.license_window import LicenseWindow
        LicenseWindow(self, self.license_manager, self.update_license_ui)
        
    def update_license_ui(self):
        is_valid, exp_str, days = self.license_manager.get_license_status()
        if is_valid:
            self.license_label.configure(text=f"라이센스: {days}일 남음\n({exp_str.split(' ')[0]})")
            
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

    def save_settings_event(self, event):
        self.save_settings()

    def save_settings(self, event=None):
        try:
            self.config_manager.set("headless", self.headless_var.get())
            
            width_val = self.min_size_entry.get()
            self.config_manager.set("min_width", int(width_val) if width_val.isdigit() else 0)
            
            dl = self.delay_slider.get()
            self.config_manager.set("delay_level", dl)
            self.config_manager.set("random_delay_min", dl * 0.5)
            self.config_manager.set("random_delay_max", dl * 0.5 + 1.0)
            
            # Save new filters/auth state
            self.config_manager.set("ext_jpg", self.ext_jpg.get())
            self.config_manager.set("ext_png", self.ext_png.get())
            self.config_manager.set("ext_webp", self.ext_webp.get())
            self.config_manager.set("ext_gif", self.ext_gif.get())
            self.config_manager.set("exclude_keywords", self.exclude_entry.get())
            
            self.config_manager.set("manual_login", self.login_var.get())
            wait_val = self.login_wait_entry.get()
            self.config_manager.set("login_wait", int(wait_val) if wait_val.isdigit() else 30)
            
            self.config_manager.set("use_pagination", self.paging_var.get())
            self.config_manager.set("pagination_selector", self.paging_entry.get())
            
            self.logger.info("Settings updated.")
        except Exception as e:
            self.logger.error(f"Save settings error: {e}")

    def start_crawling_thread(self):
        url = self.url_entry.get()
        if not url:
            self.append_log("Error: Please enter a URL.")
            return
            
        self.stop_event.clear()
        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.status_label.configure(text="상태: 수집 중...", text_color="#00FFAA")
        self.progress_bar.set(0) # Reset progress
        self.progress_bar.start() # Start indeterminate progress during crawl
        
        self.append_log(f"\n========================================")
        
        # Logic to start crawling thread...
        self.append_log(f"Starting crawl for: {url}")
        
        # Simulating threaded task
        t = threading.Thread(target=self.run_crawler, daemon=True)
        t.start()
        
    def stop_crawling(self):
        self.append_log("\n[중지 요청됨] 작업들을 안전하게 멈추는 중입니다. 잠시 대기해주세요...")
        self.stop_event.set()
        self.stop_button.configure(state="disabled")
        
    def run_crawler(self):
        url = self.url_entry.get().strip()
        if not url:
            return
            
        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url
            self.after(0, lambda: self.url_entry.delete(0, 'end'))
            self.after(0, lambda: self.url_entry.insert(0, url))

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

            images = crawler.crawl(url, target_selector=target_selector, max_depth=max_depth, progress_callback=progress_callback, stop_event=self.stop_event)
            
            if self.stop_event.is_set():
                self.after(0, lambda: self.append_log("크롤링이 중지되었습니다."))
                self.after(0, lambda: self.finish_crawling())
                return
            
            if not images:
                self.after(0, lambda: self.append_log("이미지를 찾을 수 없거나 수집에 실패했습니다."))
                self.after(0, lambda: self.finish_crawling())
                return

            self.after(0, lambda: self.append_log(f"크롤링 완료. 이미지 {len(images)}개를 발견했습니다."))
            
            self.after(0, lambda: self.progress_bar.stop())
            self.after(0, lambda: self.progress_bar.set(0.5))
            
            # 3. Download Images
            self.after(0, lambda: self.append_log("이미지 다운로드 시작... (다중 스레드)"))
            save_dir = downloader.process_images(images, base_result_dir="results", progress_callback=lambda p: self.after(0, lambda: self.progress_bar.set(0.5 + p*0.5)), stop_event=self.stop_event)
            
            if self.stop_event.is_set():
                self.after(0, lambda: self.append_log("다운로드가 중지되었습니다."))
                self.after(0, lambda: self.finish_crawling())
                return
            
            if save_dir:
                self.after(0, lambda: self.append_log(f"완료! 저장 위치: {save_dir}"))
                self.after(0, lambda: self.progress_bar.set(1.0))
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
