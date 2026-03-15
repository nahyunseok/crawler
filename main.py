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
    
    # 라이선스 클라이언트 초기화 (구글 스프레드시트 기반)
    license_client = OnlineLicenseClient(LICENSE_SERVER_URL)
    version = get_version()

    # ──────────────────────────────────────────────────
    # Fast Path: 이미 동의 + 라이선스 캐시 유효 → 바로 메인 화면
    # 숨긴 root를 만들지 않아서 customtkinter 내부 after-script 에러 방지
    # ──────────────────────────────────────────────────
    if DisclaimerWindow.has_agreed():
        cached = license_client.check_local_validity()
        if cached and cached.get("valid"):
            # root 없이 바로 메인 화면 진입 (가장 일반적인 경로)
            app = MainWindow(license_client, version)
            app.mainloop()
            return

    # ──────────────────────────────────────────────────
    # Slow Path: 이용약관 동의 또는 라이선스 인증이 필요한 경우
    # root를 숨긴 컨테이너로 사용하고, Toplevel 창을 띄운다
    # ──────────────────────────────────────────────────
    root = ctk.CTk()
    root.withdraw()  # 숨김 (Toplevel창의 부모 역할만)

    # 앱 아이콘 설정
    icon_path = resource_path("app_icon.ico")
    if os.path.exists(icon_path):
        root.iconbitmap(icon_path)

    def start_main_app():
        """라이선스 인증 완료 후 메인 화면으로 진입"""
        try:
            root.destroy()
        except Exception:
            pass
        app = MainWindow(license_client, version)
        app.mainloop()
        sys.exit(0)  # 프로세스 완전 종료 (root.mainloop()으로 돌아가지 않게)

    def start_license_check():
        """라이선스 인증 단계"""
        cached = license_client.check_local_validity()
        if cached and cached.get("valid"):
            start_main_app()
        else:
            LicenseWindow(root, license_client, start_main_app)

    # 이용약관 동의 여부에 따라 분기
    if DisclaimerWindow.has_agreed():
        # 동의는 했지만 라이선스가 만료/미인증인 경우
        start_license_check()
    else:
        # 첫 실행: 이용약관 → 라이선스 → 메인
        DisclaimerWindow(root, start_license_check)

    root.mainloop()


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    main()
