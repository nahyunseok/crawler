import customtkinter as ctk
from src.utils.logger import get_logger
from src.utils.config_manager import ConfigManager, delay_bounds, resolve_data_dir
from src.ui.dialogs import show_info, show_warning, show_error, ask_yes_no
import threading
import os
import sys

def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)


# 크롤링 깊이 — 화면에 보이는 글자와 저장되는 숫자의 대응표
# ⛔ 수정금지(DO NOT MODIFY — INTENDED): 이 대응은 여기 한 곳에만 둔다.
#    화면 문구를 그대로 settings.json 에 저장하면, 나중에 문구만 다듬어도
#    옛 저장본을 못 읽어 설정이 조용히 초기화된다. 그래서 '숫자'로 저장한다.
DEPTH_LABELS = ("1단계 (현재)", "2단계 (링크)")

# ──────────────────────────────────────────────────────────────
# 설정 탭 공통 레이아웃 규격
# ⛔ 수정금지(DO NOT MODIFY — INTENDED): 설정 탭의 모든 줄은 이 규격만 쓴다.
# 왜: 예전에는 탭마다 입력칸 폭(60/200/250/320/350)과 여백(2/5/(8,5)/(15,5)/(20,5))이
#     제각각이어서, 탭을 바꿀 때마다 다른 화면처럼 보였다. 규격을 상수로 고정하면
#     새 설정을 추가해도 저절로 같은 모양이 된다(매직넘버 금지 + 시각적 일관성).
# ──────────────────────────────────────────────────────────────
FORM_TAB_HEIGHT = 200        # 탭 높이 — 탭을 바꿔도 박스 크기가 변하지 않도록 고정한다
FORM_ROWS_PER_TAB = 4        # 세 탭 모두 4줄 (아래가 텅 비는 탭이 없도록 맞춤)
FORM_LABEL_WIDTH = 96        # 라벨 열 고정 폭 — 이게 있어야 입력칸 시작선이 세로로 정렬된다
FORM_LABEL_GAP = 10          # 라벨 열과 컨트롤 열 사이
FORM_ROW_PAD_Y = 6           # 줄 간 세로 간격 (모든 줄 동일)
FORM_PAD_X = 10              # 탭 내부 좌우 여백

FIELD_GAP = 6                # 같은 묶음 안 위젯 사이
FIELD_GROUP_GAP = 22         # 다른 묶음 사이 (예: 체크박스 두 개를 구분)
FIELD_W_TINY = 62            # 숫자 입력 (크기·초·페이지수)
FIELD_W_CHECK = 62           # 확장자 체크박스
FIELD_W_MEDIUM = 190         # 슬라이더·중간 길이 입력
FIELD_W_LONG = 250           # 선택자 입력
FIELD_W_WIDE = 320           # 키워드 입력

# 비활성 상태 색 — '지금은 안 쓰이는 입력칸'임을 눈에 보이게 한다
HINT_TEXT_COLOR = "gray45"
DISABLED_TEXT_COLOR = "gray35"
DISABLED_BORDER_COLOR = "gray28"


def depth_label_for(depth_value):
    """저장된 숫자(1/2) → 화면 문구"""
    try:
        return DEPTH_LABELS[1] if int(depth_value) >= 2 else DEPTH_LABELS[0]
    except (TypeError, ValueError):
        return DEPTH_LABELS[0]


def depth_value_from(label):
    """화면 문구 → 저장할 숫자(1/2)"""
    return 2 if label == DEPTH_LABELS[1] else 1

class MainWindow(ctk.CTk):
    def __init__(self, license_client, version="2.0.0"):
        super().__init__()

        self.logger = get_logger()
        self.config_manager = ConfigManager()
        self.license_client = license_client  # 구글 스프레드시트 기반 라이선스 클라이언트
        self.version = version

        self.stop_event = threading.Event()
        # 입력칸의 원래 색과 안내 문구 라벨을 기억해 두는 곳 (비활성 표시를 되돌릴 때 쓴다)
        self._entry_default_colors = {}
        self._field_hints = {}
        # 딜레이 슬라이더의 마지막 단계 — 드래그 중 같은 값으로 반복 저장되는 것을 막는다
        # (설정 파일을 손으로 고쳐 null 이나 문자열이 들어와도 죽지 않게 방어한다)
        try:
            self._last_delay_level = int(round(float(self.config_manager.get("delay_level"))))
        except (TypeError, ValueError):
            self._last_delay_level = 2
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

    def _form_row(self, tab, row_index, label_text):
        """
        설정 탭의 한 줄(라벨 + 컨트롤 자리)을 만들고, 컨트롤을 담을 프레임을 돌려준다.

        ⛔ 수정금지(DO NOT MODIFY — INTENDED)
        무엇: 설정 탭의 모든 줄은 반드시 이 함수로 만든다.
        왜:   세 탭이 각자 다른 방식으로 배치되어 있었다. 라벨 열이 없는 탭, 입력칸 폭이
              줄마다 다른 탭, 2줄뿐인 탭이 섞여 있어서 탭 버튼을 누를 때마다 다른 화면처럼
              보였다. 라벨 열 폭·줄 간격을 한 함수가 정하면 그 문제가 구조적으로 사라진다.
        건드리면: 새 설정을 추가할 때마다 배치가 조금씩 어긋나 일관성이 다시 무너진다.
        """
        tab.grid_columnconfigure(1, weight=1)
        # 모든 줄이 같은 높이를 갖도록 고정 (탭을 바꿔도 줄 위치가 흔들리지 않는다)
        tab.grid_rowconfigure(row_index, minsize=FORM_TAB_HEIGHT // (FORM_ROWS_PER_TAB + 1))

        ctk.CTkLabel(
            tab, text=label_text, width=FORM_LABEL_WIDTH, anchor="w",
            font=ctk.CTkFont(size=12, weight="bold"), text_color="gray70"
        ).grid(row=row_index, column=0, sticky="w",
               padx=(FORM_PAD_X, FORM_LABEL_GAP), pady=FORM_ROW_PAD_Y)

        holder = ctk.CTkFrame(tab, fg_color="transparent")
        holder.grid(row=row_index, column=1, sticky="w",
                    padx=(0, FORM_PAD_X), pady=FORM_ROW_PAD_Y)
        return holder

    def _attach_hint(self, entry, string_var, hint_text):
        """
        입력칸이 비어 있을 때 회색 안내 문구를 겹쳐 보여준다.

        ⛔ 수정금지(DO NOT MODIFY / DO NOT REVERT TO placeholder_text — INTENDED)
        무엇: customtkinter 의 placeholder_text 를 믿지 않고 직접 안내 문구를 얹는다.
        왜:   CTkEntry 내부 조건이 이렇게 되어 있다(ctk_entry.py):
                  if ... and (self._textvariable is None or self._textvariable == "")
              여기서 self._textvariable 은 StringVar '객체' 인데 "" 문자열과 비교하므로
              항상 False 다. 즉 이 프로그램처럼 모든 입력칸에 textvariable 을 연결하면
              placeholder 가 단 한 번도 표시되지 않는다. 실제로 주소·선택자·키워드 칸이
              전부 빈 상자로만 보여서 무엇을 넣어야 하는지 알 수 없었다.
              textvariable 은 입력 유실 방지를 위해 반드시 유지해야 하므로(전역수칙 4),
              placeholder 쪽을 직접 구현하는 것이 맞다.
        건드리면: 안내 문구가 다시 전부 사라진다(입력칸이 그냥 빈 상자가 된다).
        """
        # ⛔ 부모를 반드시 entry 로 둔다(entry.master 가 아니다).
        #    customtkinter 의 fg_color="transparent" 는 '진짜 투명'이 아니라 '부모 배경색으로 칠하기'다.
        #    부모를 바깥 프레임으로 두면 라벨이 입력칸 위에 '탭 배경색 사각형'을 그려서
        #    입력칸 왼쪽이 잘려 보였다(실제로 그렇게 만들어 보고 확인함).
        # ⛔ fg_color 를 "transparent" 로 두지 말고 입력칸의 '실제 색'을 그대로 지정한다.
        #    transparent 는 부모 색을 추정해 칠하는데, CTkEntry 안에서는 그 추정값이
        #    입력칸 내부색과 미세하게 달라 문구 뒤에 사각형이 보였다(캡처로 확인함).
        hint = ctk.CTkLabel(
            entry, text=hint_text, text_color=HINT_TEXT_COLOR,
            font=ctk.CTkFont(size=12), anchor="w", fg_color=entry.cget("fg_color")
        )
        # 비활성 상태가 되면 이 문구도 함께 흐려지도록 기억해 둔다
        self._field_hints[entry] = hint

        def 갱신(*_args):
            try:
                if string_var.get():
                    hint.place_forget()
                else:
                    # 입력칸 위에 겹쳐 놓는다 (값 자체는 건드리지 않으므로 설정에 섞이지 않는다)
                    hint.place(x=12, rely=0.5, anchor="w")
            except Exception:
                pass

        # 문구를 클릭해도 입력칸에 커서가 가도록
        hint.bind("<Button-1>", lambda _e: entry.focus_set())
        # ⛔ add="+" 로 붙인다. 기존 <FocusOut> 저장 콜백을 덮어쓰면 설정이 저장되지 않는다.
        entry.bind("<FocusIn>", lambda _e: hint.place_forget(), add="+")
        entry.bind("<FocusOut>", lambda _e: 갱신(), add="+")
        string_var.trace_add("write", 갱신)
        갱신()
        return hint

    def create_widgets(self):
        # --- UI Variables Binding (안정성 규칙 4 준수: 입력 유실 방지) ---
        self.url_var = ctk.StringVar(value="")
        # ⛔ 여기서는 get() 에 기본값을 따로 적지 않는다.
        #    기본값은 config_manager.default_config '한 곳'에만 둔다.
        #    (예전에는 min_width 기본값이 UI 에서 200, default_config 에서 100 으로 두 벌이었다)
        self.scope_text_var = ctk.StringVar(value=self.config_manager.get("scope_selector"))
        self.min_width_var = ctk.StringVar(value=str(self.config_manager.get("min_width")))
        self.min_height_var = ctk.StringVar(value=str(self.config_manager.get("min_height")))
        self.exclude_var = ctk.StringVar(value=self.config_manager.get("exclude_keywords"))
        self.include_var = ctk.StringVar(value=self.config_manager.get("include_keywords"))
        self.login_wait_var = ctk.StringVar(value=str(self.config_manager.get("login_wait")))
        self.paging_entry_var = ctk.StringVar(value=self.config_manager.get("pagination_selector"))
        # 최대 순회 페이지 — 예전에는 settings.json 을 직접 열어야만 바꿀 수 있었다
        self.max_pages_var = ctk.StringVar(value=str(self.config_manager.get("max_pagination_pages")))

        # --- Sidebar ---
        self.sidebar_frame = ctk.CTkFrame(self, width=200, corner_radius=0)
        self.sidebar_frame.grid(row=0, column=0, rowspan=4, sticky="nsew")
        # 4행이 남는 공간을 모두 차지해서 버전 정보를 맨 아래로 밀어낸다
        self.sidebar_frame.grid_rowconfigure(4, weight=1)

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

        # ⛔ 수정금지(DO NOT MODIFY / DO NOT ADD BACK — INTENDED)
        # 무엇: 여기에 있던 '이어받기 기록 초기화' 버튼을 의도적으로 제거했다.
        # 왜:   ① '필터 및 고급' 탭의 [이어받기(중복 제외) 사용] 체크를 해제하면
        #          똑같이 처음부터 다시 받을 수 있어 기능이 완전히 중복이었다.
        #       ② 그 버튼은 '모든 사이트'의 기록을 한꺼번에 지웠다. 한 사이트를 다시 받고 싶을 뿐인데
        #          다른 사이트 기록까지 잃는, 되돌릴 수 없는 위험한 동작이었다.
        #       ③ 긴 버튼 텍스트 때문에 사이드바 폭이 불필요하게 넓어져 있었다.
        # 기록 정리가 정말 필요하면 ImageDownloader.clear_history() 를 쓴다(지원 목적).
        # 하단 버전 정보 & 저작권 (사이드바 맨 아래)
        self.version_label = ctk.CTkLabel(
            self.sidebar_frame,
            text=f"v{self.version}\n© 2026 Gemini Soft.",
            font=ctk.CTkFont(size=10),
            text_color="gray50"
        )
        self.version_label.grid(row=5, column=0, padx=20, pady=(0, 15), sticky="s")

        # --- Main Input Area ---
        self.main_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.main_frame.grid(row=0, column=1, padx=20, pady=20, sticky="nsew")

        self.url_label = ctk.CTkLabel(self.main_frame, text="수집할 주소(URL):", font=ctk.CTkFont(size=14))
        self.url_label.grid(row=0, column=0, sticky="w", pady=(0, 5))

        # placeholder_text 는 textvariable 과 함께 쓰면 표시되지 않는다 → _attach_hint 로 대체
        self.url_entry = ctk.CTkEntry(self.main_frame, width=500, textvariable=self.url_var)
        self.url_entry.grid(row=1, column=0, sticky="ew", pady=(0, 20))
        self._attach_hint(self.url_entry, self.url_var, "https://example.com")

        # Action Buttons
        self.button_frame = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        self.button_frame.grid(row=2, column=0, sticky="ew")

        self.start_button = ctk.CTkButton(self.button_frame, text="🚀 수집 시작", font=ctk.CTkFont(size=15, weight="bold"), height=40, command=self.start_crawling_thread)
        self.start_button.pack(side="left", padx=(0, 10))

        self.stop_button = ctk.CTkButton(self.button_frame, text="🛑 중지", font=ctk.CTkFont(size=15, weight="bold"), height=40, fg_color="red", hover_color="darkred", state="disabled", command=self.stop_crawling)
        self.stop_button.pack(side="left", padx=(0, 10))

        # ⛔ 같은 줄의 버튼 3개는 높이·폰트를 동일하게 유지한다(시각적 일관성).
        #    예전에는 이 버튼만 bold 가 아니어서 같은 줄에서 글자 굵기가 달라 보였다.
        self.open_result_button = ctk.CTkButton(self.button_frame, text="📁 결과 폴더 열기", font=ctk.CTkFont(size=15, weight="bold"), height=40, fg_color="gray", hover_color="gray30", command=self.open_results_folder)
        self.open_result_button.pack(side="left")

        # --- Settings Area (Tabs) ---
        # ⛔ 수정금지(DO NOT MODIFY — INTENDED): 세 탭은 모두 _form_row() 로만 줄을 만든다.
        # 무엇: '라벨 열 + 컨트롤 열' 2단 구조, 같은 줄 간격, 같은 입력칸 폭 규격을 공유한다.
        # 왜:   예전에는 탭마다 배치 방식이 달랐다.
        #       · 일반 설정   : 라벨 없이 좌측 흐름 배치(3줄)
        #       · 필터 및 고급 : 입력칸 폭이 350/320/60 으로 제각각, 여백도 5/(15,5)/(20,5)/(8,5)/2
        #       · 계정 및 접속 : 2줄뿐이라 아래가 텅 비어 밀도가 확 달라짐
        #       그래서 탭 버튼을 누를 때마다 구조가 바뀌는 느낌이 났다(실제 사용자 지적).
        # 건드리면: 탭 간 일관성이 다시 깨진다. 새 설정을 넣을 때도 _form_row 를 쓸 것.
        self.settings_tabs = ctk.CTkTabview(self.main_frame, height=FORM_TAB_HEIGHT)
        self.settings_tabs.grid(row=3, column=0, sticky="ew", pady=(10, 0))

        tab_basic = self.settings_tabs.add("일반 설정")
        tab_filter = self.settings_tabs.add("필터 및 고급")
        tab_auth = self.settings_tabs.add("접속 및 순회")

        # ── Tab 1: 일반 설정 ──────────────────────────────────
        row = self._form_row(tab_basic, 0, "브라우저")
        self.headless_var = ctk.BooleanVar(value=self.config_manager.get("headless"))
        self.headless_check = ctk.CTkCheckBox(row, text="화면 숨기기 (빠름 / 추적 위험)",
                                              variable=self.headless_var, command=self.save_settings)
        self.headless_check.pack(side="left")

        row = self._form_row(tab_basic, 1, "안전 딜레이")
        self.delay_slider = ctk.CTkSlider(row, from_=1, to=5, number_of_steps=4,
                                          width=FIELD_W_MEDIUM, command=self.on_delay_change)
        self.delay_slider.set(self.config_manager.get("delay_level"))
        self.delay_slider.pack(side="left")
        # 슬라이더 값이 '실제 몇 초'인지 그 자리에서 보여준다 (표시=동작 일치)
        self.delay_readout = ctk.CTkLabel(row, text="", font=ctk.CTkFont(size=12),
                                          text_color="gray60", anchor="w")
        self.delay_readout.pack(side="left", padx=(FIELD_GAP, 0))

        row = self._form_row(tab_basic, 2, "수집 정책")
        self.robots_var = ctk.BooleanVar(value=self.config_manager.get("respect_robots"))
        self.robots_check = ctk.CTkCheckBox(row, text="robots.txt 준수 (권장)",
                                            variable=self.robots_var, command=self.on_robots_toggle)
        self.robots_check.pack(side="left")

        self.resume_var = ctk.BooleanVar(value=self.config_manager.get("use_resume"))
        self.resume_check = ctk.CTkCheckBox(row, text="이어받기 (중복 제외)",
                                            variable=self.resume_var, command=self.save_settings)
        self.resume_check.pack(side="left", padx=(FIELD_GROUP_GAP, 0))

        row = self._form_row(tab_basic, 3, "수집 범위")
        self.scope_var = ctk.BooleanVar(value=self.config_manager.get("use_scope"))
        self.scope_check = ctk.CTkCheckBox(row, text="특정 영역만",
                                           variable=self.scope_var, command=self.on_dependency_toggle)
        self.scope_check.pack(side="left")
        # ⛔ 이 입력칸은 '항상 같은 자리에' 보이게 둔다(숨기지 않는다).
        #    예전에는 체크할 때 pack() 으로 뒤늦게 추가해서 pack 순서상 맨 끝에 붙었고,
        #    자기 체크박스 옆이 아니라 엉뚱한 위치에 나타나며 줄 전체가 밀렸다.
        self.scope_entry = ctk.CTkEntry(row, width=FIELD_W_LONG, textvariable=self.scope_text_var)
        self.scope_entry.pack(side="left", padx=(FIELD_GAP, 0))
        self.scope_entry.bind("<FocusOut>", self.save_settings)
        self._attach_hint(self.scope_entry, self.scope_text_var, "예: #content 또는 .gallery-grid")

        # ── Tab 2: 필터 및 고급 ───────────────────────────────
        row = self._form_row(tab_filter, 0, "최소 크기")
        self.min_width_entry = ctk.CTkEntry(row, width=FIELD_W_TINY, textvariable=self.min_width_var)
        self.min_width_entry.pack(side="left")
        self.min_width_entry.bind("<FocusOut>", self.save_settings)
        ctk.CTkLabel(row, text="×", text_color="gray60").pack(side="left", padx=FIELD_GAP)
        self.min_height_entry = ctk.CTkEntry(row, width=FIELD_W_TINY, textvariable=self.min_height_var)
        self.min_height_entry.pack(side="left")
        self.min_height_entry.bind("<FocusOut>", self.save_settings)
        ctk.CTkLabel(row, text="px 이상만 수집", text_color="gray60").pack(side="left", padx=(FIELD_GAP, 0))

        row = self._form_row(tab_filter, 1, "허용 확장자")
        self.ext_jpg = ctk.BooleanVar(value=self.config_manager.get("ext_jpg"))
        self.ext_png = ctk.BooleanVar(value=self.config_manager.get("ext_png"))
        self.ext_webp = ctk.BooleanVar(value=self.config_manager.get("ext_webp"))
        self.ext_gif = ctk.BooleanVar(value=self.config_manager.get("ext_gif"))
        for text, var in (("JPG", self.ext_jpg), ("PNG", self.ext_png),
                          ("WEBP", self.ext_webp), ("GIF", self.ext_gif)):
            ctk.CTkCheckBox(row, text=text, variable=var, width=FIELD_W_CHECK,
                            command=self.save_settings).pack(side="left", padx=(0, FIELD_GAP))

        row = self._form_row(tab_filter, 2, "제외 키워드")
        self.exclude_entry = ctk.CTkEntry(row, width=FIELD_W_WIDE, textvariable=self.exclude_var)
        self.exclude_entry.pack(side="left")
        self.exclude_entry.bind("<FocusOut>", self.save_settings)
        self._attach_hint(self.exclude_entry, self.exclude_var, "예: logo, icon, banner (비우면 제외 없음)")

        row = self._form_row(tab_filter, 3, "필수 포함")
        self.include_entry = ctk.CTkEntry(row, width=FIELD_W_WIDE, textvariable=self.include_var)
        self.include_entry.pack(side="left")
        self.include_entry.bind("<FocusOut>", self.save_settings)
        self._attach_hint(self.include_entry, self.include_var, "예: 풍경, 사람 (비우면 모두 수집)")

        # ── Tab 3: 접속 및 순회 ───────────────────────────────
        row = self._form_row(tab_auth, 0, "수동 로그인")
        self.login_var = ctk.BooleanVar(value=self.config_manager.get("manual_login"))
        self.login_check = ctk.CTkCheckBox(row, text="로그인 대기",
                                           variable=self.login_var, command=self.on_manual_login_toggle)
        self.login_check.pack(side="left")
        self.login_wait_entry = ctk.CTkEntry(row, width=FIELD_W_TINY, textvariable=self.login_wait_var)
        self.login_wait_entry.pack(side="left", padx=(FIELD_GAP, 0))
        self.login_wait_entry.bind("<FocusOut>", self.save_settings)
        ctk.CTkLabel(row, text="초 동안", text_color="gray60").pack(side="left", padx=(FIELD_GAP, 0))

        row = self._form_row(tab_auth, 1, "크롤링 깊이")
        self.depth_var = ctk.StringVar(value=depth_label_for(self.config_manager.get("crawl_depth")))
        self.depth_segment = ctk.CTkSegmentedButton(row, values=list(DEPTH_LABELS),
                                                    variable=self.depth_var,
                                                    command=self.save_settings_event)
        self.depth_segment.pack(side="left")

        row = self._form_row(tab_auth, 2, "페이지 순회")
        self.paging_var = ctk.BooleanVar(value=self.config_manager.get("use_pagination"))
        self.paging_check = ctk.CTkCheckBox(row, text="'다음 페이지' 자동 클릭",
                                            variable=self.paging_var, command=self.on_dependency_toggle)
        self.paging_check.pack(side="left")
        self.paging_entry = ctk.CTkEntry(row, width=FIELD_W_MEDIUM, textvariable=self.paging_entry_var)
        self.paging_entry.pack(side="left", padx=(FIELD_GAP, 0))
        self.paging_entry.bind("<FocusOut>", self.save_settings)
        self._attach_hint(self.paging_entry, self.paging_entry_var, "예: a.next, #btnNext")

        row = self._form_row(tab_auth, 3, "최대 순회")
        self.max_pages_entry = ctk.CTkEntry(row, width=FIELD_W_TINY, textvariable=self.max_pages_var)
        self.max_pages_entry.pack(side="left")
        self.max_pages_entry.bind("<FocusOut>", self.save_settings)
        ctk.CTkLabel(row, text="페이지까지", text_color="gray60").pack(side="left", padx=(FIELD_GAP, 0))

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

        # 종속 입력칸(영역 선택자·로그인 대기시간·페이지 선택자)의 활성/비활성 상태를 처음에 한 번 맞춘다
        self._apply_dependency_states()
        # 슬라이더 옆 '실제 몇 초' 표시도 시작할 때 한 번 맞춘다
        self._update_delay_readout(self._last_delay_level)

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

    def on_robots_toggle(self):
        """robots.txt 준수 해제 시 법적 책임을 명확히 고지한다 (전역수칙 9)."""
        if not self.robots_var.get():
            agreed = ask_yes_no(
                self,
                "robots.txt 무시 경고",
                "robots.txt는 사이트 운영자가 '자동 수집을 원하지 않는다'고 밝힌 규약입니다.\n\n"
                "이를 무시하고 수집할 경우 발생하는 모든 법적·민사적 책임(IP 차단, "
                "저작권 분쟁 등)은 전적으로 사용자 본인에게 있습니다.\n\n"
                "본인이 권한을 가졌거나 수집 허가를 받은 사이트인가요?",
                kind="warning",
                yes_text="네, 계속",
                no_text="아니오",
                danger=True,      # 되돌리기 어려운 선택이므로 빨간 버튼으로 한 번 더 경고
            )
            if not agreed:
                self.robots_var.set(True)
        self.save_settings()

    def on_manual_login_toggle(self):
        """수동 로그인을 켜면 화면 숨기기와 충돌하므로 안내한다."""
        if self.login_var.get() and self.headless_var.get():
            show_info(
                self,
                "화면 숨기기를 해제했습니다",
                "수동 로그인은 브라우저 화면이 보여야 사용할 수 있습니다.\n"
                "'화면 숨기기' 옵션을 자동으로 해제했습니다."
            )
            self.headless_var.set(False)
        # 로그인 대기시간 입력칸의 활성 상태도 함께 맞춘다 (다른 종속 입력칸과 같은 규칙)
        self._apply_dependency_states()
        self.save_settings()

    # ──────────────────────────────────────────────────────────
    # 종속 입력칸 상태 관리
    # ──────────────────────────────────────────────────────────
    def _apply_dependency_states(self):
        """
        '체크박스를 켜야 의미가 있는 입력칸'들의 활성/비활성을 한꺼번에 맞춘다.

        ⛔ 수정금지(DO NOT MODIFY — INTENDED)
        무엇: 종속 입력칸을 숨기거나 다시 배치하지 않는다. 항상 같은 자리에 두고
              꺼져 있으면 '비활성(회색)'으로만 표시한다.
        왜:   예전에는 규칙이 세 가지로 갈려 있어 화면이 일관되지 않았다.
              · 영역 선택자   → 체크할 때마다 없던 칸이 튀어나와 줄 전체가 밀렸다(위치도 엉뚱했다)
              · 로그인 대기시간 → 옵션이 꺼져 있어도 입력이 가능해, 적힌 값이 무시되는 줄 몰랐다
              · 페이지 선택자   → 같은 문제
              비활성 표시는 레이아웃을 흔들지 않으면서 '지금은 안 쓰인다'를 정확히 알려준다.
        건드리면: 체크 한 번에 UI가 출렁이거나, 무시되는 값을 사용자가 계속 입력하게 된다.
        """
        pairs = (
            (self.scope_entry, self.scope_var.get()),
            (self.login_wait_entry, self.login_var.get()),
            (self.paging_entry, self.paging_var.get()),
        )
        for widget, enabled in pairs:
            try:
                # 원래 색을 처음 한 번만 기억해 둔다 (되돌릴 때 쓴다)
                if widget not in self._entry_default_colors:
                    self._entry_default_colors[widget] = {
                        "text": widget.cget("text_color"),
                        "border": widget.cget("border_color"),
                    }
                기본색 = self._entry_default_colors[widget]

                # ⛔ 수정금지(DO NOT MODIFY — INTENDED): state 만 바꾸면 안 된다.
                #    CTkEntry 는 state="disabled" 로만 두면 화면이 활성 상태와 '픽셀 단위로 동일'하다
                #    (캡처를 비교해 확인함). 그러면 사용자는 입력해도 무시되는 칸인 줄 모르고
                #    계속 값을 적어 넣는다 — 표시와 동작이 어긋나는 상태다.
                #    그래서 글자색과 테두리색까지 함께 흐리게 만들어 '지금은 안 쓰인다'를 눈에 보이게 한다.
                if enabled:
                    widget.configure(state="normal",
                                     text_color=기본색["text"],
                                     border_color=기본색["border"])
                else:
                    widget.configure(state="disabled",
                                     text_color=DISABLED_TEXT_COLOR,
                                     border_color=DISABLED_BORDER_COLOR)

                # 안내 문구도 같이 흐려져야 한 덩어리로 보인다
                hint = self._field_hints.get(widget)
                if hint is not None:
                    hint.configure(text_color=HINT_TEXT_COLOR if enabled else DISABLED_TEXT_COLOR)
            except Exception:
                pass

    def on_dependency_toggle(self):
        """종속 입력칸을 가진 체크박스를 눌렀을 때 — 상태를 맞추고 저장한다."""
        self._apply_dependency_states()
        self.save_settings()

    def get_results_dir(self):
        """
        결과 저장 폴더.
        ⛔ 설정·로그와 동일한 규칙(resolve_data_dir)을 쓴다. 쓰기 권한이 없는 위치에
           설치된 경우 사용자 데이터 폴더로 자동 대체된다.
        """
        return resolve_data_dir("results")

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

    def _update_delay_readout(self, level):
        """슬라이더 옆에 '실제 몇 초로 동작하는지'를 표시한다."""
        low, high = delay_bounds(level)
        try:
            self.delay_readout.configure(text=f"{int(level)}단계 · 요청 간격 {low:.1f}~{high:.1f}초")
        except Exception:
            pass

    def on_delay_change(self, _value=None):
        """
        안전 딜레이 슬라이더가 움직였을 때.

        ⛔ 수정금지(DO NOT MODIFY — INTENDED): 값이 '실제로 바뀐 경우에만' 저장한다.
        왜:   슬라이더 command 는 드래그하는 동안 마우스가 움직일 때마다 호출된다.
              그대로 저장하면 단계가 그대로인데도 settings.json 을 수십 번 다시 쓴다.
              (set_many 로 1회 쓰기로 줄여 놓은 개선이 여기서 다시 무의미해진다)
        건드리면: 슬라이더를 한 번 끌 때마다 불필요한 디스크 쓰기가 폭증한다.
        """
        level = int(round(self.delay_slider.get()))
        self._update_delay_readout(level)
        if level == self._last_delay_level:
            return
        self._last_delay_level = level
        self.save_settings()

    def _read_int_field(self, string_var, field_label, config_key):
        """
        숫자 입력칸을 읽는다. 숫자가 아니면 '직전에 저장된 값'을 유지하고 화면에 알린다.

        ⛔ 수정금지(DO NOT MODIFY — INTENDED)
        무엇: 잘못된 입력을 0 이나 기본값으로 조용히 바꾸지 않는다.
        왜:   예전에는 `int(v) if v.isdigit() else 0` 이어서, 최소 이미지 크기 칸에
              'abc'·'-5'·'10.5' 같은 값을 넣으면 말없이 0 이 되어 크기 필터가 통째로 꺼졌다.
              사용자는 1×1 추적 픽셀까지 전부 수집되는 이유를 알 수 없었다(침묵 축소).
        건드리면: 오타 하나로 필터가 꺼지고, 그 사실이 아무 데도 드러나지 않는다.
        """
        raw = string_var.get().strip()
        if raw.isdigit():
            return int(raw)

        kept = self.config_manager.get(config_key)
        # 입력칸도 실제 적용값으로 되돌려 '표시=동작'을 맞춘다
        string_var.set(str(kept))
        self.append_log(
            f"⚠️ '{field_label}' 에 숫자가 아닌 값('{raw}')이 입력되어 무시했습니다. "
            f"→ 이전 값 {kept} 을(를) 그대로 사용합니다."
        )
        return kept

    def save_settings(self, event=None):
        """
        화면의 입력값 전체를 설정 파일에 저장한다.

        ⛔ 수정금지(DO NOT MODIFY — INTENDED): set() 을 항목별로 부르지 말고
           반드시 set_many() 로 '한 번에' 저장해야 한다.
           예전에는 set() 을 18번 호출해서 settings.json 을 18번 덮어썼고,
           슬라이더를 움직일 때마다 이 쓰기가 반복되어 파일 손상 위험이 컸다.
        """
        try:
            # ⛔ 침묵 축소 금지: 숫자가 아닌 값이 들어오면 조용히 0/기본값으로 바꾸지 않고 알린다.
            #    예전에는 최소 크기 칸에 'abc' 를 넣으면 말없이 0 이 되어 필터가 사실상 꺼졌고,
            #    사용자는 1×1 추적픽셀까지 전부 수집되는 이유를 알 수 없었다.
            width_val = self._read_int_field(self.min_width_var, "최소 이미지 크기(가로)", "min_width")
            height_val = self._read_int_field(self.min_height_var, "최소 이미지 크기(세로)", "min_height")
            wait_val = self._read_int_field(self.login_wait_var, "로그인 대기 시간", "login_wait")
            max_pages_val = self._read_int_field(self.max_pages_var, "최대 순회 페이지", "max_pagination_pages")

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
                "min_width": width_val,
                "min_height": height_val,
                "ext_jpg": self.ext_jpg.get(),
                "ext_png": self.ext_png.get(),
                "ext_webp": self.ext_webp.get(),
                "ext_gif": self.ext_gif.get(),
                "exclude_keywords": self.exclude_var.get(),
                "include_keywords": self.include_var.get(),

                # 계정 및 접속
                "manual_login": self.login_var.get(),
                "login_wait": wait_val,
                "use_pagination": self.paging_var.get(),
                "pagination_selector": self.paging_entry_var.get(),
                "max_pagination_pages": max_pages_val,

                # 수집 정책
                "respect_robots": self.robots_var.get(),
                "use_resume": self.resume_var.get(),

                # 수집 범위 — 다른 설정과 마찬가지로 기억해 둔다(예전에는 이 3개만 저장되지 않았다)
                "use_scope": self.scope_var.get(),
                "scope_selector": self.scope_text_var.get(),
                "crawl_depth": depth_value_from(self.depth_var.get()),
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
            show_warning(self, "주소를 입력해주세요", "수집할 페이지의 주소(URL)를 먼저 입력해주세요.")
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
            # ⛔ 침묵 실패 금지: '특정 영역만 수집'을 켰는데 선택자가 비어 있으면
            #    조용히 페이지 전체를 수집한다. 사용자는 영역 제한이 걸린 줄 알고 있었다.
            target_selector = self.scope_text_var.get().strip() if self.scope_var.get() else None
            if self.scope_var.get() and not target_selector:
                self.ui_call(lambda: self.append_log(
                    "⚠️ '특정 영역만 수집'이 켜져 있지만 CSS 선택자가 비어 있어 "
                    "페이지 전체를 수집합니다. ([일반 설정] 탭에서 선택자를 입력해주세요)"))

            # Get Depth — 화면 문구 → 숫자 변환은 depth_value_from() 한 곳에서만 한다
            #             (예전에는 여기서 "2단계" 문자열을 직접 찾아, 문구를 다듬으면 조용히 깨졌다)
            max_depth = depth_value_from(self.depth_var.get())

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
                # 건너뛴 이유를 화면 로그에 그대로 보여준다 (몇 개가 왜 빠졌는지 반드시 밝힌다)
                message_callback=progress_callback,
            )

            if self.stop_event.is_set():
                self.ui_call(lambda: self.append_log("다운로드가 중지되었습니다."))
                return

            if save_dir:
                self.ui_call(lambda: self.append_log(f"완료! 저장 위치: {save_dir}"))
                self.ui_call(lambda: self.progress_bar.set(1.0))
                self.ui_call(lambda: self.show_success_dialog(save_dir))
            else:
                # ⛔ 안내 문구는 실제로 존재하는 UI 만 가리켜야 한다.
                #    (예전에는 이미 없어진 '이어받기 기록 초기화' 버튼을 안내했다)
                self.ui_call(lambda: self.append_log(
                    "새로 저장된 이미지가 없습니다.\n"
                    "→ 이미 모두 받았을 수 있습니다. 처음부터 다시 받으려면 '일반 설정' 탭의 "
                    "[이어받기(중복 제외) 사용] 체크를 해제하고 다시 시도해주세요.\n"
                    "→ 또는 최소 이미지 크기/확장자 필터가 너무 엄격하지 않은지 확인해주세요."))

        except PermissionError as e:
            # robots.txt 차단 — 사용자가 이해할 수 있는 안내를 그대로 보여준다
            msg = str(e)
            self.logger.warning(f"Blocked by robots.txt: {url}")
            self.ui_call(lambda: self.append_log(f"⛔ {msg}"))
            self.ui_call(lambda: show_warning(self, "수집이 차단되었습니다", msg))

        except BaseException as e:
            # 크롬 드라이버 오류는 원인별 안내 문구를 그대로 노출한다
            user_msg = getattr(e, "user_message", None)
            self.logger.error(f"Critical error in crawler thread: {e}", exc_info=True)

            if user_msg:
                self.ui_call(lambda: self.append_log(f"⚠️ {user_msg}"))
                self.ui_call(lambda: show_error(self, "실행 오류", user_msg))
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
