"""
라이선스 인증 다이얼로그 (구글 스프레드시트 온라인 인증)
Golden_Keyword 프로젝트에서 이식 후 Gemini Image Crawler에 맞게 조정
"""
import customtkinter as ctk
from tkinter import messagebox
from datetime import datetime
import json
import os
import sys
import threading


def resource_path(relative_path):
    """PyInstaller 환경과 개발 환경 모두에서 리소스 경로를 올바르게 반환"""
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)


class LicenseWindow(ctk.CTkToplevel):
    """
    라이선스 인증 다이얼로그 (상용 수준)
    - 구글 스프레드시트 기반 온라인 인증
    - 기기 바인딩으로 불법 복제 차단
    - 키 마스킹(***) 및 Brute Force 방지
    - 비동기 인증 (UI 프리징 방지)
    """
    
    def __init__(self, parent, license_client, on_success_callback):
        super().__init__(parent)
        
        self.client = license_client
        self.on_success_callback = on_success_callback
        
        # Brute Force 방지 변수
        self.failed_attempts = 0
        self.lockout_time = 0
        
        self.title("🔐 Gemini Image Crawler - 라이선스 인증")
        self.geometry("500x420")
        self.resizable(False, False)
        
        # 아이콘 설정
        icon_path = resource_path("app_icon.ico")
        if os.path.exists(icon_path):
            self.iconbitmap(icon_path)
        
        # 화면 중앙 배치
        self.update_idletasks()
        x = (self.winfo_screenwidth() // 2) - (500 // 2)
        y = (self.winfo_screenheight() // 2) - (420 // 2)
        self.geometry(f"+{x}+{y}")
        
        # 모달 처리
        self.transient(parent)
        self.grab_set()
        
        # 닫기 버튼 가로채기 (인증 없이 종료)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        
        self._create_widgets()
        self._load_cached_info()

    def _create_widgets(self):
        """UI 위젯 구성"""
        # 메인 컨테이너
        main_frame = ctk.CTkFrame(self)
        main_frame.pack(fill="both", expand=True, padx=20, pady=20)
        
        # 타이틀
        ctk.CTkLabel(
            main_frame,
            text="🔐 정품 인증",
            font=ctk.CTkFont(size=20, weight="bold")
        ).pack(pady=(15, 5))
        
        # 안내 메시지
        info_text = (
            "• 1 PC 1 라이선스 정책 (다른 PC 이동 시 초기화 필요)\n"
            "• 라이선스 만료일 자정(00:00:00)에 즉시 사용이 중단됩니다.\n"
            "• 구매 및 연장 문의: 카톡친구 아이디 gost1227"
        )
        ctk.CTkLabel(
            main_frame,
            text=info_text,
            font=ctk.CTkFont(family="맑은 고딕", size=11),
            text_color="gray70",
            justify="left"
        ).pack(padx=15, pady=(5, 15))
        
        # 상태 표시 영역
        status_frame = ctk.CTkFrame(main_frame, fg_color=("gray95", "gray20"))
        status_frame.pack(fill="x", padx=15, pady=(0, 15))
        
        self.status_label = ctk.CTkLabel(
            status_frame,
            text="상태: 라이선스 키가 필요합니다.",
            font=ctk.CTkFont(family="맑은 고딕", size=12),
            text_color="#f39c12"
        )
        self.status_label.pack(fill="x", pady=8)
        
        self.expiry_label = ctk.CTkLabel(
            status_frame,
            text="만료일: -",
            font=ctk.CTkFont(family="맑은 고딕", size=12)
        )
        self.expiry_label.pack(fill="x", pady=(0, 8))
        
        # 구분선
        ctk.CTkFrame(main_frame, height=2, fg_color="gray50").pack(fill="x", padx=15, pady=10)
        
        # 키 입력 라벨
        ctk.CTkLabel(
            main_frame,
            text="라이선스 키 입력:",
            font=ctk.CTkFont(family="맑은 고딕", size=12, weight="bold"),
            anchor="w"
        ).pack(fill="x", padx=15, pady=(0, 5))
        
        # 키 입력 프레임 (입력창 + 눈 버튼)
        input_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        input_frame.pack(fill="x", padx=15, pady=(0, 10))
        
        self.key_entry = ctk.CTkEntry(
            input_frame,
            placeholder_text="발급받은 키를 입력하세요",
            show="*",
            font=ctk.CTkFont(size=13)
        )
        self.key_entry.pack(side="left", fill="x", expand=True, padx=(0, 5))
        
        # 키 보이기/숨기기 토글 버튼
        self.toggle_btn = ctk.CTkButton(
            input_frame,
            text="👁️",
            width=40,
            height=28,
            fg_color="#95a5a6",
            hover_color="#7f8c8d",
            command=self._toggle_visibility
        )
        self.toggle_btn.pack(side="right")
        
        # 버튼 영역
        btn_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        btn_frame.pack(fill="x", padx=15, pady=(5, 10))
        
        # 인증하기 버튼 (중요하니까 크고 눈에 띄게)
        self.verify_btn = ctk.CTkButton(
            btn_frame,
            text="✅ 인증하기",
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color="#27ae60",
            hover_color="#2ecc71",
            height=40,
            command=self._activate_license
        )
        self.verify_btn.pack(side="left", fill="x", expand=True, padx=(0, 5))
        
        # 종료 버튼
        self.exit_btn = ctk.CTkButton(
            btn_frame,
            text="종료",
            font=ctk.CTkFont(size=14),
            fg_color="red",
            hover_color="darkred",
            height=40,
            width=80,
            command=self._on_close
        )
        self.exit_btn.pack(side="right")

    def _load_cached_info(self):
        """
        이전에 캐시된 키가 있으면 입력창에 보여주고 상태만 표시.
        자동으로 서버 검증하지 않음 — 사용자가 다른 키로 변경할 수 있어야 하므로.
        """
        try:
            if os.path.exists(self.client.cache_file):
                with open(self.client.cache_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    cached_key = data.get("key", "")
                    if cached_key:
                        self.key_entry.insert(0, cached_key)
                        # 로컬 캐시 정보만 표시 (서버 통신 없음)
                        cached_result = self.client.check_local_validity()
                        if cached_result and cached_result.get("valid"):
                            exp_data = cached_result.get("data", {})
                            raw_expiry = exp_data.get("expiration", "-")
                            if "T" in raw_expiry:
                                raw_expiry = raw_expiry.split("T")[0]
                            self.status_label.configure(
                                text="상태: ✅ 인증됨 (캐시)",
                                text_color="#2ecc71"
                            )
                            self.expiry_label.configure(text=f"만료일: {raw_expiry}")
                        else:
                            self.status_label.configure(
                                text="상태: 키가 만료되었거나 재인증이 필요합니다.",
                                text_color="#f39c12"
                            )
        except Exception:
            pass

    def _activate_license(self):
        """인증하기 버튼 클릭 시"""
        # Brute Force 잠금 확인
        if self.failed_attempts >= 5:
            remaining = int(self.lockout_time - datetime.now().timestamp())
            if remaining > 0:
                messagebox.showwarning(
                    "입력 제한",
                    f"보안을 위해 잠시 입력이 제한되었습니다.\n{remaining}초 후 다시 시도해주세요.",
                    parent=self
                )
                return
            else:
                self.failed_attempts = 0  # 잠금 해제
        
        key = self.key_entry.get().strip()
        
        # 입력값 검증
        if not key:
            messagebox.showwarning("입력 확인", "라이선스 키를 입력해주세요.", parent=self)
            return
            
        if len(key) < 5:
            messagebox.showwarning(
                "입력 확인",
                "유효하지 않은 라이선스 키 형식입니다.\n정확히 입력했는지 확인해주세요.",
                parent=self
            )
            return
        
        # UI 비활성화 (중복 클릭 방지)
        self.key_entry.configure(state="disabled")
        self.verify_btn.configure(state="disabled")
        self.status_label.configure(text="상태: ⏳ 서버 확인 중...", text_color="#f39c12")
        
        # 비동기 인증 실행 (UI 프리징 방지)
        threading.Thread(target=self._run_verification, args=(key,), daemon=True).start()

    def _run_verification(self, key):
        """백그라운드 스레드에서 서버 인증 수행"""
        try:
            result = self.client.verify(key)
            # 윈도우가 아직 살아있는 경우에만 UI 업데이트
            if self.winfo_exists():
                self.after(0, lambda: self._handle_result(result))
        except Exception as e:
            if self.winfo_exists():
                self.after(0, lambda: self._handle_error(str(e)))

    def _handle_result(self, result):
        """인증 결과 처리 (메인 스레드)"""
        # 윈도우가 이미 파괴되었으면 아무것도 하지 않음
        if not self.winfo_exists():
            return
            
        # UI 다시 활성화
        self.key_entry.configure(state="normal")
        self.verify_btn.configure(state="normal")
        
        if result.get("valid"):
            # 성공!
            data = result.get("data", {})
            raw_expiry = data.get("expiration", "-")
            if "T" in raw_expiry:
                raw_expiry = raw_expiry.split("T")[0]
                
            self.status_label.configure(
                text=f"상태: ✅ {result['message']}",
                text_color="#2ecc71"
            )
            self.expiry_label.configure(text=f"만료일: {raw_expiry}")
            self.failed_attempts = 0  # 성공 시 카운터 초기화

            
            messagebox.showinfo("성공", "인증되었습니다!\n이제 정상적으로 사용 가능합니다.", parent=self)
            
            # 메인 앱으로 진행
            self.on_success_callback()
            self.destroy()
        else:
            # 실패
            self.status_label.configure(
                text=f"상태: ❌ {result['message']}",
                text_color="#e74c3c"
            )
            
            self.failed_attempts += 1
            if self.failed_attempts >= 5:
                self.lockout_time = datetime.now().timestamp() + 60  # 60초 잠금
                messagebox.showerror(
                    "인증 실패",
                    f"인증 실패: {result['message']}\n\n⚠️ 연속된 실패로 1분간 입력이 제한됩니다.",
                    parent=self
                )
            else:
                messagebox.showerror(
                    "실패",
                    f"인증 실패: {result['message']}\n(남은 시도 횟수: {5 - self.failed_attempts}회)",
                    parent=self
                )

    def _handle_error(self, error_msg):
        """인증 중 예외 발생 시 처리"""
        if not self.winfo_exists():
            return
        self.key_entry.configure(state="normal")
        self.verify_btn.configure(state="normal")
        self.status_label.configure(text="상태: ⚠️ 오류 발생", text_color="#e74c3c")
        messagebox.showerror("오류", f"인증 과정에서 오류가 발생했습니다.\n{error_msg}", parent=self)

    def _toggle_visibility(self):
        """라이선스 키 보이기/숨기기 토글"""
        current_show = self.key_entry.cget("show")
        if current_show == "*":
            self.key_entry.configure(show="")
            self.toggle_btn.configure(text="🔒", fg_color="#e74c3c", hover_color="#c0392b")
        else:
            self.key_entry.configure(show="*")
            self.toggle_btn.configure(text="👁️", fg_color="#95a5a6", hover_color="#7f8c8d")

    def _on_close(self):
        """라이선스 인증 없이 창을 닫으면 프로그램 전체 종료"""
        if messagebox.askyesno(
            "종료",
            "라이선스 인증을 완료해야 프로그램을 사용할 수 있습니다.\n종료하시겠습니까?",
            parent=self
        ):
            self.destroy()
            try:
                self.master.destroy()
            except Exception:
                pass
            sys.exit(0)
