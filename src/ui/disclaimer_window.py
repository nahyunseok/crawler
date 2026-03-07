import customtkinter as ctk
import os
import json
import sys
from appdirs import user_data_dir

def resource_path(relative_path):
    """PyInstaller 환경과 개발 환경 모두에서 리소스 경로를 올바르게 반환"""
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)


# 면책 조항 전문 (프로그램 내 하드코딩 — 별도 파일 의존성 제거)
DISCLAIMER_TEXT = """
『Gemini 이미지 수집기』 이용약관 및 면책 조항

제1조 (목적)
본 약관은 "Gemini 이미지 수집기"(이하 "프로그램") 사용에 관한 
조건 및 절차를 규정함을 목적으로 합니다.

제2조 (면책 조항)
① 본 프로그램의 사용으로 인해 발생하는 모든 문제(계정 정지, 
   IP 차단, 지적 재산권 침해 분쟁, 금전적 손실 등)에 대한 
   민/형사상 책임은 전적으로 사용자 본인에게 있습니다.
② 개발자는 프로그램의 오작동, 데이터 손실, 서비스 중단 등으로 
   인한 직접적/간접적 손해에 대해 책임을 지지 않습니다.

제3조 (사용자의 의무)
① 사용자는 대상 웹사이트의 robots.txt 정책 및 이용약관을 
   반드시 확인하고 준수해야 합니다.
② 타인의 저작물을 무단으로 수집, 복제, 배포하는 행위는 
   관련 법률에 의해 처벌될 수 있습니다.
③ 수집한 데이터의 활용에 대한 모든 법적 책임은 
   사용자 본인에게 있습니다.

제4조 (라이센스)
① 본 프로그램은 구매자 1인 1기기에 한하여 사용이 허가됩니다.
② 라이센스 키의 공유, 양도, 재배포는 엄격히 금지됩니다.
③ 프로그램의 역공학, 디컴파일, 소스코드 추출을 금지합니다.

제5조 (저작권)
본 프로그램의 모든 지적 재산권은 개발자에게 있으며, 
무단 복제 및 배포를 금지합니다.

═══════════════════════════════════════
위 약관에 동의하셔야 프로그램을 사용하실 수 있습니다.
""".strip()


class DisclaimerWindow(ctk.CTkToplevel):
    """
    첫 실행 시 이용약관 동의를 받는 모달 창.
    동의 상태를 로컬 사용자 데이터 폴더에 저장하여
    이후 실행 시에는 다시 묻지 않는다.
    """

    # 동의 상태 저장 경로 (appdirs 기반)
    APP_NAME = "GeminiImageCrawler"
    APP_AUTHOR = "User"

    def __init__(self, parent, on_agree_callback):
        super().__init__(parent)

        self.on_agree_callback = on_agree_callback

        self.title("이용약관 및 면책 조항")
        self.geometry("550x520")
        self.resizable(False, False)

        # 아이콘 설정
        icon_path = resource_path("app_icon.ico")
        if os.path.exists(icon_path):
            self.iconbitmap(icon_path)

        # 화면 중앙에 배치
        self.update_idletasks()
        x = (self.winfo_screenwidth() // 2) - (550 // 2)
        y = (self.winfo_screenheight() // 2) - (520 // 2)
        self.geometry(f"+{x}+{y}")

        # 모달 처리 (이 창을 닫기 전까지 부모 창 사용 불가)
        self.transient(parent)
        self.grab_set()

        # 닫기 버튼 가로채기
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self._create_widgets()

    def _create_widgets(self):
        """UI 위젯 구성"""
        # 상단 타이틀
        title_label = ctk.CTkLabel(
            self,
            text="📋 이용약관 및 면책 조항",
            font=ctk.CTkFont(size=18, weight="bold")
        )
        title_label.pack(pady=(20, 10))

        # 이용약관 텍스트 박스 (읽기 전용)
        self.text_box = ctk.CTkTextbox(
            self,
            width=500,
            height=300,
            font=ctk.CTkFont(family="맑은 고딕", size=12),
            wrap="word"
        )
        self.text_box.pack(padx=20, pady=(0, 10))
        self.text_box.insert("1.0", DISCLAIMER_TEXT)
        self.text_box.configure(state="disabled")  # 읽기 전용

        # 동의 체크박스
        self.agree_var = ctk.BooleanVar(value=False)
        self.agree_check = ctk.CTkCheckBox(
            self,
            text="위 이용약관에 모두 동의합니다.",
            variable=self.agree_var,
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self._toggle_button
        )
        self.agree_check.pack(pady=(5, 10))

        # 버튼 프레임
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(pady=(0, 20))

        # 동의 후 계속 버튼 (체크 전에는 비활성화)
        self.agree_btn = ctk.CTkButton(
            btn_frame,
            text="동의하고 계속하기",
            font=ctk.CTkFont(size=14, weight="bold"),
            state="disabled",
            command=self._on_agree
        )
        self.agree_btn.pack(side="left", padx=10)

        # 종료 버튼
        self.exit_btn = ctk.CTkButton(
            btn_frame,
            text="동의하지 않음 (종료)",
            font=ctk.CTkFont(size=14),
            fg_color="red",
            hover_color="darkred",
            command=self._on_close
        )
        self.exit_btn.pack(side="left", padx=10)

    def _toggle_button(self):
        """체크박스 상태에 따라 '동의' 버튼 활성화/비활성화"""
        if self.agree_var.get():
            self.agree_btn.configure(state="normal")
        else:
            self.agree_btn.configure(state="disabled")

    def _on_agree(self):
        """사용자가 동의했을 때: 동의 사실을 파일로 저장하고 콜백 호출"""
        self._save_agreement()
        # 반드시 자신(Toplevel)을 먼저 파괴한 뒤 콜백 호출
        # 콜백 안에서 root.destroy()가 일어날 수 있으므로, 순서가 중요하다
        self.destroy()
        self.on_agree_callback()

    def _on_close(self):
        """동의하지 않고 창을 닫으면 프로그램 전체 종료"""
        sys.exit(0)

    # ──────────────────────────────────────────────
    # 동의 상태 저장/로드 (클래스 메서드)
    # ──────────────────────────────────────────────

    @classmethod
    def _get_agreement_path(cls):
        """동의 상태 파일 경로 반환"""
        data_dir = user_data_dir(cls.APP_NAME, cls.APP_AUTHOR)
        os.makedirs(data_dir, exist_ok=True)
        return os.path.join(data_dir, "disclaimer_agreed.json")

    @classmethod
    def has_agreed(cls):
        """이전에 동의한 적이 있는지 확인"""
        path = cls._get_agreement_path()
        if not os.path.exists(path):
            return False
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return data.get("agreed", False)
        except Exception:
            return False

    def _save_agreement(self):
        """동의 상태를 파일로 저장"""
        from datetime import datetime
        path = self._get_agreement_path()
        data = {
            "agreed": True,
            "agreed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "version": "2.0"
        }
        try:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
        except Exception:
            pass  # 저장 실패해도 프로그램 진행은 허용
