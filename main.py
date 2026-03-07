import os
import sys
from src.ui.main_window import MainWindow
from src.ui.license_window import LicenseWindow
from src.ui.disclaimer_window import DisclaimerWindow
from src.core.license_client import OnlineLicenseClient
import customtkinter as ctk
from src.utils.logger import setup_logger

# 구글 Apps Script URL (라이선스 서버)
LICENSE_SERVER_URL = "https://script.google.com/macros/s/AKfycbx3iE6LTtTPpdqOUhAm51sdqL-m3yDENVFBHOpikjYE2_SCT4rhPb3f9NyJW1bdFwV9/exec"


def resource_path(relative_path):
    """PyInstaller 환경과 개발 환경 모두에서 리소스 경로를 올바르게 반환"""
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)


def get_version():
    """version.txt에서 현재 버전을 읽어 반환"""
    version_path = resource_path("version.txt")
    try:
        with open(version_path, "r") as f:
            return f.read().strip()
    except Exception:
        return "2.0.0"


def main():
    # 로거 초기화
    setup_logger()
    
    # GUI 프레임워크 기본 설정
    ctk.set_appearance_mode("Dark")
    ctk.set_default_color_theme("blue")
    
    root = ctk.CTk()
    root.withdraw()  # 루트 창을 숨김 (보이지 않는 컨테이너 역할)
    
    # 앱 아이콘 설정
    icon_path = resource_path("app_icon.ico")
    if os.path.exists(icon_path):
        root.iconbitmap(icon_path)
    
    # 라이선스 클라이언트 초기화 (구글 스프레드시트 기반)
    license_client = OnlineLicenseClient(LICENSE_SERVER_URL)
    
    version = get_version()

    # ──────────────────────────────────────────────────
    # 앱 시작 플로우: 이용약관 동의 → 라이선스 인증 → 메인 화면
    # ──────────────────────────────────────────────────

    def start_main_app():
        """라이선스 인증 완료 후 메인 화면으로 진입"""
        try:
            root.destroy()  # 루트 컨테이너 해제 (이미 해제되었을 수 있음)
        except Exception:
            pass
        app = MainWindow(license_client, version)
        app.mainloop()
        # 메인 윈도우가 닫히면 프로세스 완전 종료
        # 이것이 없으면 root.mainloop() (83줄)이 파괴된 root에서 호출되어 크래시
        sys.exit(0)

    def start_license_check():
        """라이선스 인증 단계 — 로컬 캐시가 유효하면 바로 메인 화면"""
        cached = license_client.check_local_validity()
        if cached and cached.get("valid"):
            start_main_app()
        else:
            LicenseWindow(root, license_client, start_main_app)

    # 1단계: 이용약관 동의 여부 확인
    if DisclaimerWindow.has_agreed():
        # 이미 동의한 사용자 → 바로 라이선스 단계로
        start_license_check()
    else:
        # 첫 실행 → 이용약관 동의 팝업 표시
        DisclaimerWindow(root, start_license_check)

    root.mainloop()


if __name__ == "__main__":
    main()
