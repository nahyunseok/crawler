"""[desktop-exe] 배포 자원 충돌 점검 — 운영 중인 exe 가 dist/ 를 잠그고 있는지.

build.py 의 clean_build() 는 dist/ 를 통째로 rmtree 한다. 그때 배포판 exe 가 실행 중이면
윈도우가 폴더를 잠그고 있어서 빌드가 중간에 깨진다(버전만 올라가고 산출물은 없는 최악의 상태).

⛔ 러너 내장 검사(_check_exe_not_running)를 쓰지 않는 이유:
   이 프로젝트의 exe 이름에는 버전이 붙는다(Gemini_Image_Crawler_v1.0.16.exe).
   내장 검사는 IMAGENAME 완전일치라서 버전이 바뀌면 '실행 중이 아님'으로 조용히 통과한다.
   그래서 여기서 프리픽스로 모든 버전을 잡는다.
"""
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
EXE_PREFIX = "Gemini_Image_Crawler"


def _실행중인_배포판_exe():
    """이름이 EXE_PREFIX 로 시작하는 프로세스 목록을 돌려준다."""
    if sys.platform != "win32":
        return []

    # tasklist 출력은 시스템 코드페이지(한글 윈도우=CP949)라 UTF-8 로 강제 디코딩하면 깨진다
    # → 바이트로 받아 관대하게 디코딩한다(찾는 이름은 ASCII 라 손상되지 않는다)
    raw = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True).stdout or b""
    이름들 = []
    for line in raw.decode("utf-8", errors="ignore").splitlines():
        if not line.startswith('"'):
            continue
        name = line.split('","')[0].lstrip('"')
        if name.startswith(EXE_PREFIX):
            이름들.append(name)
    return 이름들


def test_배포판_exe_가_실행중이_아니다():
    실행중 = _실행중인_배포판_exe()
    assert not 실행중, (
        f"배포판 exe 가 실행 중입니다: {', '.join(실행중)}\n"
        f"   ↳ dist/ 폴더가 잠겨 클린 빌드가 실패합니다. 해당 프로그램을 먼저 종료하세요.\n"
        f"   ↳ (python.exe 를 통째로 종료하지 말 것 — 이 점검 스크립트까지 죽는다)"
    )


def test_빌드에_필요한_리소스_파일이_모두_있다():
    """PyInstaller 의 --add-data 로 넘기는 파일이 없으면 빌드는 성공하지만
    실행 시 아이콘·버전 표시가 조용히 깨진다."""
    필수_리소스 = ["app_icon.ico", "version.txt", "main.py", "build.py"]
    없는것 = [f for f in 필수_리소스 if not (ROOT / f).exists()]
    assert not 없는것, f"빌드 리소스가 없습니다: {없는것}"


def test_버전파일_형식이_Semantic_Versioning_이다():
    """build.py 의 bump_version() 은 'a.b.c' 를 가정한다. 형식이 깨지면 1.0.1 로 리셋된다."""
    version = (ROOT / "version.txt").read_text(encoding="utf-8").strip()
    parts = version.split(".")

    assert len(parts) == 3, f"version.txt 형식이 잘못됐습니다: {version!r} (a.b.c 여야 함)"
    assert all(p.isdigit() for p in parts), f"버전에 숫자가 아닌 값이 있습니다: {version!r}"


@pytest.mark.parametrize("모듈", [
    "customtkinter", "selenium", "undetected_chromedriver", "fake_useragent",
    "webdriver_manager", "bs4", "pandas", "openpyxl", "PIL", "requests", "appdirs",
])
def test_번들해야_할_의존성이_설치되어_있다(모듈):
    """설치 안 된 채 빌드하면 exe 는 만들어지지만 실행 즉시 ImportError 로 죽는다."""
    __import__(모듈)


def test_삭제된_모듈을_참조하는_코드가_남아있지_않다():
    """v1.0.16 에서 license_manager.py 를 지웠다. 남은 import 가 있으면 exe 실행이 즉사한다."""
    남은_참조 = []
    for py in list(ROOT.glob("*.py")) + list((ROOT / "src").rglob("*.py")):
        text = py.read_text(encoding="utf-8", errors="ignore")
        if "license_manager" in text or "LicenseManager" in text:
            남은_참조.append(str(py.relative_to(ROOT)))
    assert not 남은_참조, f"삭제된 license_manager 를 참조하는 파일: {남은_참조}"


def test_모든_소스가_문법오류_없이_컴파일된다():
    """빌드 전 최소 방어선 — 문법 오류는 PyInstaller 가 잡아주지 않는다."""
    r = subprocess.run(
        [sys.executable, "-m", "compileall", "-q", str(ROOT / "main.py"), str(ROOT / "src")],
        capture_output=True,
    )
    assert r.returncode == 0, f"컴파일 실패:\n{(r.stdout + r.stderr).decode('utf-8', errors='ignore')}"
