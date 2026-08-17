import customtkinter as ctk
from src.utils.logger import get_logger
from src.utils.config_manager import ConfigManager, delay_bounds
from tkinter import messagebox
import threading
import os
import sys

def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

class MainWindow(ctk.CTk):
    def __init__(self, license_client, version="2.0.0"):
        super().__init__()

        self.logger = get_logger()
        self.config_manager = ConfigManager()
        self.license_client = license_client  # 구글 스프레드시트 기반 라이선스 클라이언트
        self.version = version

        self.stop_event = threading.Event()
        # 창이 이미 닫혔는지 표시 (백그라운드 스레드가 죽은 위젯을 건드리지 않도록)
        self._is_closed = False

        # Window Setup — 타이틀에 버전 정보 표시
        self.title(f"Gemini Image Crawler v{self.version}")
        self.geometry("900x760")

        icon_path = resource_path("app_icon.ico")
        if os.path.exists(icon_path):
            self.iconbitmap(icon_path)

        # Grid Configuration
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=0) # Header/Input
        self.grid_rowconfigure(1, weight=1) # Main Content (Log/Results)

        self.protocol("WM_DELETE_WINDOW", self.on_closing)

        self.create_widgets()

    # ──────────────────────────────────────────────────────────
    # 스레드 → UI 안전 호출 헬퍼
    # ──────────────────────────────────────────────────────────
    def ui_call(self, func):
        """
        백그라운드 스레드에서 UI를 갱신할 때 쓰는 안전 래퍼.
        ⛔ 창이 이미 닫힌 뒤에 self.after 를 호출하면 TclError 가 연쇄로 터진다.
           (수집 중 X 버튼을 누르면 재현됐던 문제)
        """
        if self._is_closed:
            return
        try:
            self.after(0, func)
        except Exception:
            # 창이 파괴되는 순간과 겹친 경우 — 무시하는 것이 정상
            pass

    def on_closing(self):
        """Called when the user clicks the 'X' button to close the window."""
        self._is_closed = True
        self.stop_event.set() # Stop any running threads cleanly
        self.destroy()

    def create_widgets(self):
        # --- UI Variables Binding (안정성 규칙 4 준수: 입력 유실 방지) ---
        self.url_var = ctk.StringVar(value="")
        self.scope_text_var = ctk.StringVar(value="")
        self.min_width_var = ctk.StringVar(value=str(self.config_manager.get("min_width", 200)))
        self.min_height_var = ctk.StringVar(value=str(self.config_manager.get("min_height", 200)))
        self.exclude_var = ctk.StringVar(value=self.config_manager.get("exclude_keywords", "logo, icon, button, tracker, pixel, banner"))
        self.include_var = ctk.StringVar(value=self.config_manager.get("include_keywords", ""))
        self.login_wait_var = ctk.StringVar(value=str(self.config_manager.get("login_wait", 30)))
        self.paging_entry_var = ctk.StringVar(value=self.config_manager.get("pagination_selector", ""))

        # --- Sidebar ---
        self.sidebar_frame = ctk.CTkFrame(self, width=200, corner_radius=0)
        self.sidebar_frame.grid(row=0, column=0, rowspan=4, sticky="nsew")
        self.sidebar_frame.grid_rowconfigure(5, weight=1)

        self.logo_label = ctk.CTkLabel(self.sidebar_frame, text="Gemini\n이미지 수집기", font=ctk.CTkFont(size=24, weight="bold"))
        self.logo_label.grid(row=0, column=0, padx=20, pady=(30, 10))

        self.status_label = ctk.CTkLabel(self.sidebar_frame, text="상태: 준비됨", text_color="gray", font=ctk.CTkFont(size=14))
        self.status_label.grid(row=1, column=0, padx=20, pady=10)

        # 라이선스 상태 표시 (구글 스프레드시트 기반)
        is_valid, exp_str, days = self.license_client.get_license_status()
        lic_text = f"라이센스: {days}일 남음\n({exp_str})" if is_valid else "라이센스: 미인증"
        self.license_label = ctk.CTkLabel(self.sidebar_frame, text=lic_text, font=ctk.CTkFont(size=11), text_color="lightgray")
        self.license_label.grid(row=2, column=0, padx=20, pady=(20, 5))

        self.renew_btn = ctk.CTkButton(self.sidebar_frame, text="라이센스 갱신 / 연장", font=ctk.CTkFont(size=12), fg_color="transparent", border_width=1, command=self.show_license_window)
        self.renew_btn.grid(row=3, column=0, padx=20, pady=5)

        # 이어받기 기록 초기화 (같은 사이트를 처음부터 다시 받고 싶을 때)
        self.reset_history_btn = ctk.CTkButton(
            self.sidebar_frame, text="이어받기 기록 초기화", font=ctk.CTkFont(size=12),
            fg_color="transparent", border_width=1, command=self.reset_download_history
        )
        self.reset_history_btn.grid(row=4, column=0, padx=20, pady=5)

        # 하단 버전 정보 & 저작권 (사이드바 맨 아래)
        self.version_label = ctk.CTkLabel(
            self.sidebar_frame,
            text=f"v{self.version}\n© 2026 Gemini Soft.",
            font=ctk.CTkFont(size=10),
            text_color="gray50"
        )
        self.version_label.grid(row=6, column=0, padx=20, pady=(0, 15), sticky="s")

        # --- Main Input Area ---
        self.main_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.main_frame.grid(row=0, column=1, padx=20, pady=20, sticky="nsew")

        self.url_label = ctk.CTkLabel(self.main_frame, text="수집할 주소(URL):", font=ctk.CTkFont(size=14))
        self.url_label.grid(row=0, column=0, sticky="w", pady=(0, 5))

        self.url_entry = ctk.CTkEntry(self.main_frame, placeholder_text="https://example.com", width=500, textvariable=self.url_var)
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
        self.settings_tabs = ctk.CTkTabview(self.main_frame, height=200)
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

        # robots.txt 준수 여부 (전역수칙 9: 플랫폼 규정 존중)
        self.robots_row = ctk.CTkFrame(tab_basic, fg_color="transparent")
        self.robots_row.pack(fill="x", padx=5, pady=(0, 5))

        self.robots_var = ctk.BooleanVar(value=self.config_manager.get("respect_robots", True))
        self.robots_check = ctk.CTkCheckBox(
            self.robots_row,
            text="robots.txt 정책 준수 (권장)",
            variable=self.robots_var,
            command=self.on_robots_toggle
        )
        self.robots_check.pack(side="left", padx=5)

        self.resume_var = ctk.BooleanVar(value=self.config_manager.get("use_resume", True))
        self.resume_check = ctk.CTkCheckBox(
            self.robots_row,
            text="이어받기(중복 제외) 사용",
            variable=self.resume_var,
            command=self.save_settings
        )
        self.resume_check.pack(side="left", padx=(20, 5))

        self.scope_frame = ctk.CTkFrame(tab_basic, fg_color="transparent")
        self.scope_frame.pack(fill="x", padx=5, pady=5)

        self.scope_var = ctk.BooleanVar(value=False)
        self.scope_check = ctk.CTkCheckBox(self.scope_frame, text="특정 영역만 수집", variable=self.scope_var, command=self.toggle_scope_input)
        self.scope_check.pack(side="left", padx=5)
        self.scope_entry = ctk.CTkEntry(self.scope_frame, placeholder_text="예: #content 또는 .gallery-grid", width=250, textvariable=self.scope_text_var)

        self.depth_label = ctk.CTkLabel(self.scope_frame, text="크롤링 깊이(PRO):")
        self.depth_label.pack(side="left", padx=(20, 5))
        self.depth_var = ctk.StringVar(value="1단계 (현재)")
        self.depth_segment = ctk.CTkSegmentedButton(self.scope_frame, values=["1단계 (현재)", "2단계 (링크)"], variable=self.depth_var)
        self.depth_segment.pack(side="left")

        # --- Tab 2: Filters ---
        self.filter_row1 = ctk.CTkFrame(tab_filter, fg_color="transparent")
        self.filter_row1.pack(fill="x", padx=5, pady=5)

        self.min_size_label = ctk.CTkLabel(self.filter_row1, text="최소 이미지 크기(px)  가로:")
        self.min_size_label.pack(side="left", padx=(5, 5))
        self.min_width_entry = ctk.CTkEntry(self.filter_row1, width=60, textvariable=self.min_width_var)
        self.min_width_entry.pack(side="left")
        self.min_width_entry.bind("<FocusOut>", self.save_settings)

        self.min_height_label = ctk.CTkLabel(self.filter_row1, text="세로:")
        self.min_height_label.pack(side="left", padx=(8, 5))
        self.min_height_entry = ctk.CTkEntry(self.filter_row1, width=60, textvariable=self.min_height_var)
        self.min_height_entry.pack(side="left")
        self.min_height_entry.bind("<FocusOut>", self.save_settings)

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
        self.exclude_entry = ctk.CTkEntry(self.filter_row2, placeholder_text="logo, icon, banner, ad", width=350, textvariable=self.exclude_var)
        self.exclude_entry.pack(side="left", padx=5)
        self.exclude_entry.bind("<FocusOut>", self.save_settings)

        self.filter_row3 = ctk.CTkFrame(tab_filter, fg_color="transparent")
        self.filter_row3.pack(fill="x", padx=5, pady=5)

        self.include_label = ctk.CTkLabel(self.filter_row3, text="필수 포함 키워드:")
        self.include_label.pack(side="left", padx=5)
        self.include_entry = ctk.CTkEntry(self.filter_row3, placeholder_text="예: 풍경, 사람, 리뷰 (비워두면 모두 수집)", width=320, textvariable=self.include_var)
        self.include_entry.pack(side="left", padx=5)
        self.include_entry.bind("<FocusOut>", self.save_settings)

        # --- Tab 3: Auth & Paging ---
        self.auth_row1 = ctk.CTkFrame(tab_auth, fg_color="transparent")
        self.auth_row1.pack(fill="x", padx=5, pady=5)

        self.login_var = ctk.BooleanVar(value=self.config_manager.get("manual_login", False))
        self.login_check = ctk.CTkCheckBox(self.auth_row1, text="수동 로그인 대기 활성화", variable=self.login_var, command=self.on_manual_login_toggle)
        self.login_check.pack(side="left", padx=5)

        self.login_wait_label = ctk.CTkLabel(self.auth_row1, text="대기 시간(초):")
        self.login_wait_label.pack(side="left", padx=(20, 5))
        self.login_wait_entry = ctk.CTkEntry(self.auth_row1, width=50, textvariable=self.login_wait_var)
        self.login_wait_entry.pack(side="left")
        self.login_wait_entry.bind("<FocusOut>", self.save_settings)

        self.auth_row2 = ctk.CTkFrame(tab_auth, fg_color="transparent")
        self.auth_row2.pack(fill="x", padx=5, pady=5)

        self.paging_var = ctk.BooleanVar(value=self.config_manager.get("use_pagination", False))
        self.paging_check = ctk.CTkCheckBox(self.auth_row2, text="'다음 페이지' 버튼 자동 클릭 (순회수집)", variable=self.paging_var, command=self.save_settings)
        self.paging_check.pack(side="left", padx=5)

        self.paging_entry = ctk.CTkEntry(self.auth_row2, placeholder_text="CSS 선택자 (예: a.next, #btnNext)", width=200, textvariable=self.paging_entry_var)
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

        # AI/자동화 책임 고지 (전역수칙 6: 면책 배너)
        self.notice_label = ctk.CTkLabel(
            self.log_frame,
            text="⚠️ 수집 결과의 저작권 확인과 활용 책임은 사용자 본인에게 있습니다. 대상 사이트의 이용약관을 반드시 확인하세요.",
            font=ctk.CTkFont(size=11),
            text_color="gray60",
            anchor="w"
        )
        self.notice_label.pack(fill="x", pady=(6, 0))

    # ──────────────────────────────────────────────────────────
    # 사이드바 동작
    # ──────────────────────────────────────────────────────────
    def show_license_window(self):
        """라이선스 갱신 버튼 클릭 시 라이선스 다이얼로그 표시"""
        from src.ui.license_window import LicenseWindow
        LicenseWindow(self, self.license_client, self.update_license_ui)

    def update_license_ui(self):
        """라이선스 상태 UI 갱신"""
        is_valid, exp_str, days = self.license_client.get_license_status()
        if is_valid:
            self.license_label.configure(text=f"라이센스: {days}일 남음\n({exp_str})")
        else:
            self.license_label.configure(text="라이센스: 미인증")

    def reset_download_history(self):
        """
        이어받기 기록 초기화.
        같은 사이트를 처음부터 다시 받고 싶을 때 사용한다.
        """
        if not messagebox.askyesno(
            "이어받기 기록 초기화",
            "지금까지 '이미 받은 이미지' 기록을 모두 지웁니다.\n\n"
            "다음 수집부터는 같은 이미지도 다시 받습니다.\n"
            "(이미 저장된 결과 폴더와 파일은 삭제되지 않습니다)\n\n"
            "진행하시겠습니까?",
            parent=self
        ):
            return

        from src.core.image_downloader import ImageDownloader
        try:
            removed = ImageDownloader.clear_history(self.get_results_dir())
            self.append_log(f"이어받기 기록을 초기화했습니다. (기록 파일 {removed}개 삭제)")
            messagebox.showinfo("완료", f"이어받기 기록을 초기화했습니다.\n(기록 파일 {removed}개 삭제)", parent=self)
        except Exception as e:
            self.logger.error(f"Failed to clear history: {e}")
            messagebox.showerror("오류", f"기록 초기화에 실패했습니다.\n{e}", parent=self)

    def on_robots_toggle(self):
        """robots.txt 준수 해제 시 법적 책임을 명확히 고지한다 (전역수칙 9)."""
        if not self.robots_var.get():
            agreed = messagebox.askyesno(
                "경고: robots.txt 무시",
                "robots.txt는 사이트 운영자가 '자동 수집을 원하지 않는다'고 밝힌 규약입니다.\n\n"
                "이를 무시하고 수집할 경우 발생하는 모든 법적·민사적 책임(IP 차단, "
                "저작권 분쟁 등)은 전적으로 사용자 본인에게 있습니다.\n\n"
                "본인이 권한을 가졌거나 수집 허가를 받은 사이트인가요?",
                icon="warning",
                parent=self
            )
            if not agreed:
                self.robots_var.set(True)
        self.save_settings()

    def on_manual_login_toggle(self):
        """수동 로그인을 켜면 화면 숨기기와 충돌하므로 안내한다."""
        if self.login_var.get() and self.headless_var.get():
            messagebox.showinfo(
                "안내",
                "수동 로그인은 브라우저 화면이 보여야 사용할 수 있습니다.\n"
                "'화면 숨기기' 옵션을 자동으로 해제합니다.",
                parent=self
            )
            self.headless_var.set(False)
        self.save_settings()

    def toggle_scope_input(self):
        if self.scope_var.get():
            self.scope_entry.pack(side="left", padx=10)
        else:
            self.scope_entry.pack_forget()

    def get_results_dir(self):
        """결과 저장 폴더 (실행 파일 위치 기준 절대 경로)."""
        return os.path.join(os.getcwd(), "results")

    def open_results_folder(self):
        try:
            results_dir = self.get_results_dir()
            os.makedirs(results_dir, exist_ok=True)
            os.startfile(results_dir)
        except Exception as e:
            self.logger.error(f"Failed to open folder: {e}")

    def append_log(self, message):
        if self._is_closed:
            return
        try:
            self.log_textbox.configure(state="normal")
            self.log_textbox.insert("end", message + "\n")
            self.log_textbox.see("end")
            self.log_textbox.configure(state="disabled")
        except Exception:
            pass

    # ──────────────────────────────────────────────────────────
    # 설정 저장
    # ──────────────────────────────────────────────────────────
    def save_settings_event(self, event):
        self.save_settings()

    def save_settings(self, event=None):
        """
        화면의 입력값 전체를 설정 파일에 저장한다.

        ⛔ 수정금지(DO NOT MODIFY — INTENDED): set() 을 항목별로 부르지 말고
           반드시 set_many() 로 '한 번에' 저장해야 한다.
           예전에는 set() 을 18번 호출해서 settings.json 을 18번 덮어썼고,
           슬라이더를 움직일 때마다 이 쓰기가 반복되어 파일 손상 위험이 컸다.
        """
        try:
            width_val = self.min_width_var.get().strip()
            height_val = self.min_height_var.get().strip()
            wait_val = self.login_wait_var.get().strip()

            # 딜레이 공식은 config_manager.delay_bounds() 한 곳에만 둔다 (표시=동작 일치)
            dl = self.delay_slider.get()
            delay_min, delay_max = delay_bounds(dl)

            saved = self.config_manager.set_many({
                # 브라우저 동작
                "headless": self.headless_var.get(),
                "delay_level": dl,
                "random_delay_min": delay_min,
                "random_delay_max": delay_max,

                # 이미지 필터
                "min_width": int(width_val) if width_val.isdigit() else 0,
                "min_height": int(height_val) if height_val.isdigit() else 0,
                "ext_jpg": self.ext_jpg.get(),
                "ext_png": self.ext_png.get(),
                "ext_webp": self.ext_webp.get(),
                "ext_gif": self.ext_gif.get(),
                "exclude_keywords": self.exclude_var.get(),
                "include_keywords": self.include_var.get(),

                # 계정 및 접속
                "manual_login": self.login_var.get(),
                "login_wait": int(wait_val) if wait_val.isdigit() else 30,
                "use_pagination": self.paging_var.get(),
                "pagination_selector": self.paging_entry_var.get(),

                # 수집 정책
                "respect_robots": self.robots_var.get(),
                "use_resume": self.resume_var.get(),
            })

            # ⛔ 침묵 실패 금지: 저장이 실패했으면 사용자가 반드시 알아야 한다.
            #    (예전에는 로그에만 남아서, 설정이 저장된 줄 알고 계속 쓰다가
            #     프로그램을 다시 켜면 값이 되돌아가 있는 상황이 생겼다)
            if saved is False:
                self.append_log(
                    f"⚠️ 설정을 저장하지 못했습니다: {self.config_manager.last_error}\n"
                    f"   → 이번 실행에는 적용되지만, 프로그램을 다시 켜면 되돌아갑니다.\n"
                    f"   → 프로그램을 쓰기 권한이 있는 폴더(예: 바탕화면·문서)로 옮겨주세요."
                )
            else:
                self.logger.info("Settings updated.")
        except Exception as e:
            self.logger.error(f"Save settings error: {e}")
            self.append_log(f"⚠️ 설정 저장 중 오류가 발생했습니다: {e}")

    # ──────────────────────────────────────────────────────────
    # 크롤링 실행
    # ──────────────────────────────────────────────────────────
    def start_crawling_thread(self):
        url = self.url_var.get().strip()
        if not url:
            self.append_log("오류: 수집할 주소(URL)를 입력해주세요.")
            messagebox.showwarning("입력 확인", "수집할 주소(URL)를 입력해주세요.", parent=self)
            return

        # ⛔ 수집 직전에 반드시 현재 입력값을 저장한다.
        #    입력칸은 <FocusOut> 에만 묶여 있어서, 값을 고치고 바로 시작하면
        #    예전 설정으로 수집되는 문제가 있었다. (전역수칙 4 — 입력 신뢰성)
        self.save_settings()

        self.stop_event.clear()
        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.status_label.configure(text="상태: 수집 중...", text_color="#00FFAA")
        self.progress_bar.set(0) # Reset progress
        self.progress_bar.start() # Start indeterminate progress during crawl

        self.append_log(f"\n========================================")
        self.append_log(f"Starting crawl for: {url}")

        t = threading.Thread(target=self.run_crawler, daemon=True)
        t.start()

    def stop_crawling(self):
        self.append_log("\n[중지 요청됨] 작업들을 안전하게 멈추는 중입니다. 잠시 대기해주세요...")
        self.stop_event.set()
        self.stop_button.configure(state="disabled")

    def run_crawler(self):
        url = self.url_var.get().strip()
        if not url:
            self.ui_call(self.finish_crawling)
            return

        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url
            fixed_url = url
            self.ui_call(lambda: self.url_var.set(fixed_url))

        crawler = None
        try:
            # 1. Initialize Engine
            self.ui_call(lambda: self.append_log("크롤러 엔진 초기화 중..."))
            from src.core.crawler_engine import CrawlerEngine
            from src.core.image_downloader import ImageDownloader

            crawler = CrawlerEngine(self.config_manager)
            downloader = ImageDownloader(self.config_manager)

            # 2. Start Crawling
            self.ui_call(lambda: self.append_log(f"수집 시작: {url}\n시간이 조금 걸릴 수 있습니다..."))

            # Define a progress callback to update UI from thread
            def progress_callback(msg):
                self.ui_call(lambda: self.append_log(msg))

            # Get Scope Selector
            target_selector = self.scope_text_var.get() if self.scope_var.get() else None

            # Get Depth
            depth_str = self.depth_var.get()
            max_depth = 2 if "2단계" in depth_str else 1

            if max_depth > 1:
                self.ui_call(lambda: self.append_log(f"딥 크롤링 시작 (깊이: {max_depth}). 시간이 더 소요됩니다."))

            images = crawler.crawl(url, target_selector=target_selector, max_depth=max_depth,
                                   progress_callback=progress_callback, stop_event=self.stop_event)

            if self.stop_event.is_set():
                self.ui_call(lambda: self.append_log("크롤링이 중지되었습니다."))
                return

            if not images:
                self.ui_call(lambda: self.append_log(
                    "이미지를 찾을 수 없거나 수집에 실패했습니다.\n"
                    "→ 필터(최소 크기 / 제외 키워드 / 필수 포함 키워드) 설정을 확인해보세요."))
                return

            self.ui_call(lambda: self.append_log(f"크롤링 완료. 이미지 {len(images)}개를 발견했습니다."))

            self.ui_call(self.progress_bar.stop)
            self.ui_call(lambda: self.progress_bar.set(0.5))

            # 3. Download Images (수동 로그인으로 얻은 쿠키를 그대로 넘긴다)
            self.ui_call(lambda: self.append_log("이미지 다운로드 시작... (다중 스레드)"))

            def download_progress(p):
                self.ui_call(lambda: self.progress_bar.set(0.5 + p * 0.5))

            save_dir = downloader.process_images(
                images,
                base_result_dir=self.get_results_dir(),
                progress_callback=download_progress,
                stop_event=self.stop_event,
                cookies=crawler.get_session_cookies(),
            )

            if self.stop_event.is_set():
                self.ui_call(lambda: self.append_log("다운로드가 중지되었습니다."))
                return

            if save_dir:
                self.ui_call(lambda: self.append_log(f"완료! 저장 위치: {save_dir}"))
                self.ui_call(lambda: self.progress_bar.set(1.0))
                self.ui_call(lambda: self.show_success_dialog(save_dir))
            else:
                self.ui_call(lambda: self.append_log(
                    "새로 저장된 이미지가 없습니다.\n"
                    "→ 이미 모두 받았을 수 있습니다. 다시 받으려면 좌측 '이어받기 기록 초기화'를 눌러주세요.\n"
                    "→ 또는 최소 이미지 크기/확장자 필터가 너무 엄격하지 않은지 확인해주세요."))

        except PermissionError as e:
            # robots.txt 차단 — 사용자가 이해할 수 있는 안내를 그대로 보여준다
            msg = str(e)
            self.logger.warning(f"Blocked by robots.txt: {url}")
            self.ui_call(lambda: self.append_log(f"⛔ {msg}"))
            self.ui_call(lambda: messagebox.showwarning("수집이 차단되었습니다", msg, parent=self))

        except BaseException as e:
            # 크롬 드라이버 오류는 원인별 안내 문구를 그대로 노출한다
            user_msg = getattr(e, "user_message", None)
            self.logger.error(f"Critical error in crawler thread: {e}", exc_info=True)

            if user_msg:
                self.ui_call(lambda: self.append_log(f"⚠️ {user_msg}"))
                self.ui_call(lambda: messagebox.showerror("실행 오류", user_msg, parent=self))
            else:
                detail = f"작업 중 오류가 발생했습니다.\n\n(상세: {str(e)[:200]})\n\n자세한 내용은 logs 폴더의 로그 파일을 확인해주세요."
                self.ui_call(lambda: self.append_log(f"⚠️ {detail}"))

        finally:
            # 크롬이 남아있지 않도록 확실히 정리
            if crawler:
                try:
                    crawler.close()
                except Exception:
                    pass
            self.ui_call(self.finish_crawling)

    def finish_crawling(self):
        if self._is_closed:
            return
        try:
            # ⛔ 진행바를 반드시 멈춘다. 예전에는 성공 경로에서만 stop() 을 불러서
            #    실패/중지 시 진행바가 영원히 애니메이션되는 문제가 있었다.
            self.progress_bar.stop()
        except Exception:
            pass
        self.start_button.configure(state="normal")
        self.stop_button.configure(state="disabled")
        self.status_label.configure(text="상태: 준비됨", text_color="gray")
        self.append_log("--- 작업 종료 ---")

    def show_success_dialog(self, path):
        # Open folder in Explorer
        try:
            os.startfile(path)
        except Exception:
            pass # Linux/Mac support can be added later
