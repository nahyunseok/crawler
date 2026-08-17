"""실행 흐름 전면 점검(2026-08-18)에서 고친 결함들의 회귀 방지 테스트.

'사이트 주소만 넣으면 명확하게 수집된다'가 성립하는지 흐름 전체를 따라가며 점검한 결과다.
설정 → 크롤러 → 다운로더로 값이 어떻게 흐르는지, 서로 충돌하거나 중복되는 구간이 없는지 본다.
"""
import ast
import inspect
import re
import textwrap

import pytest
from bs4 import BeautifulSoup

from src.core.crawler_engine import (
    CrawlerEngine, KNOWN_IMG_EXTS, NON_PAGE_EXTS,
    MAX_PAGES_PER_CRAWL, MIN_PAGE_LOAD_TIMEOUT, SCROLL_LOG_INTERVAL,
)
from src.core.image_downloader import ImageDownloader
from src.utils.config_manager import ConfigManager


def _코드만(대상):
    """주석과 docstring 을 걷어낸 실제 코드만 돌려준다(⛔ 주석의 '옛 코드 인용'을 오탐하지 않도록)."""
    소스 = textwrap.dedent(inspect.getsource(대상))
    tree = ast.parse(소스)
    제외 = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            if ast.get_docstring(node, clean=False) is not None:
                첫 = node.body[0]
                제외.update(range(첫.lineno, (첫.end_lineno or 첫.lineno) + 1))
    return "\n".join(줄 for i, 줄 in enumerate(소스.splitlines(), 1)
                     if i not in 제외 and not 줄.strip().startswith("#"))


def _엔진(tmp_path, **설정):
    """크롬을 띄우지 않고 순수 로직만 검사하기 위한 엔진 (드라이버 없음)."""
    cfg = ConfigManager(config_path=str(tmp_path / "config" / "settings.json"))
    if 설정:
        cfg.set_many(설정)
    engine = CrawlerEngine.__new__(CrawlerEngine)
    engine.config = cfg
    from src.utils.logger import get_logger
    engine.logger = get_logger()
    engine.driver = None
    engine.session_cookies = []
    engine._robots_cache = {}
    return engine


# ──────────────────────────────────────────────────────────────
# 1. 중복 판정 — 서로 다른 이미지를 같은 것으로 보지 않는다 (수집 손실 방지)
# ──────────────────────────────────────────────────────────────
@pytest.mark.parametrize("주소1, 주소2, 같아야_하나, 설명", [
    # 정적 이미지 파일 + 크기/캐시 파라미터 → 같은 이미지
    ("https://a.com/p.jpg?w=300", "https://a.com/p.jpg?w=600", True, "같은 파일 다른 크기"),
    ("https://a.com/p.png?v=1", "https://a.com/p.png?v=2", True, "캐시 무효화 파라미터"),
    # 동적 이미지 주소 → 쿼리가 다르면 다른 이미지
    ("https://a.com/img.php?id=1", "https://a.com/img.php?id=2", False, "게시판 동적 이미지"),
    ("https://a.com/view?f=a", "https://a.com/view?f=b", False, "확장자 없는 주소"),
    ("https://a.com/thumb?src=1&s=200", "https://a.com/thumb?src=2&s=200", False, "이미지 프록시"),
    # 기본
    ("https://a.com/1.png", "https://a.com/1.png", True, "완전히 같은 주소"),
    ("https://a.com/1.png", "https://a.com/2.png", False, "다른 파일"),
])
def test_중복판정은_동적_이미지_주소를_구분한다(tmp_path, 주소1, 주소2, 같아야_하나, 설명):
    """
    ⛔ 회귀 방지: 예전에는 쿼리스트링을 '무조건' 버렸다. 그래서 /img.php?id=1 과 ?id=2 가
       같은 키가 되어, 게시판·CDN·이미지 프록시를 쓰는 사이트에서 첫 장만 받고
       나머지를 전부 조용히 버렸다(v1.0.16 의 '수집 손실'과 같은 계열의 사고).
    """
    e = _엔진(tmp_path)
    같음 = e.dedup_key(주소1) == e.dedup_key(주소2)
    assert 같음 is 같아야_하나, f"{설명}: 중복판정={같음} (기대={같아야_하나})"


def test_data_uri_는_내용으로_중복판정한다(tmp_path):
    e = _엔진(tmp_path)
    a = "data:image/png;base64," + "A" * 400
    assert e.dedup_key(a) == e.dedup_key(a)
    assert e.dedup_key(a) != e.dedup_key("data:image/png;base64," + "B" * 400)


# ──────────────────────────────────────────────────────────────
# 2. 같은 사진을 두 번 받지 않는다 (<picture> 중복)
# ──────────────────────────────────────────────────────────────
def test_picture_안의_이미지는_한_번만_수집한다(tmp_path):
    """
    ⛔ 회귀 방지: <picture><source srcset="p.webp"><img src="p.jpg"></picture> 에서
       <img> 와 <source> 를 각각 담으면 같은 사진을 webp/jpg 로 두 번 내려받는다.
       주소가 달라서 중복 제거에도 걸리지 않아 결과 폴더에 같은 사진이 2장씩 쌓였다.
    """
    e = _엔진(tmp_path)
    html = """
    <div>
      <picture>
        <source srcset="https://a.com/p.webp 800w">
        <img src="https://a.com/p.jpg" alt="사진">
      </picture>
    </div>
    """
    soup = BeautifulSoup(html, "html.parser")
    결과 = e._extract_images(soup, "https://a.com/page", "제목")

    assert len(결과) == 1, f"같은 사진이 {len(결과)}개 수집됐다: {[i['src'] for i in 결과]}"
    assert 결과[0]["src"].endswith(".jpg"), "모든 브라우저가 쓰는 <img> 쪽을 남겨야 한다"


def test_img_없는_picture_의_source_는_그대로_수집한다(tmp_path):
    """짝 테스트 — 위 수정이 '<source> 수집 기능 자체'를 죽인 것이 아님을 증명한다."""
    e = _엔진(tmp_path)
    html = '<picture><source srcset="https://a.com/only.webp 800w"></picture>'
    결과 = e._extract_images(BeautifulSoup(html, "html.parser"), "https://a.com/p", "제목")

    assert len(결과) == 1
    assert 결과[0]["src"].endswith(".webp")


# ──────────────────────────────────────────────────────────────
# 3. 설정 충돌 — 수동 로그인 + 화면 숨기기
# ──────────────────────────────────────────────────────────────
def test_수동로그인이_켜지면_화면숨기기를_무시한다():
    """
    ⛔ 회귀 방지: 화면이 없으면 사용자가 로그인할 수 없는데, 프로그램은 대기 시간만
       흘려보내고 비로그인 상태로 수집해 회원 전용 이미지를 전부 403 으로 실패시켰다.
       UI 에서도 막지만 settings.json 을 직접 고치면 이 충돌 상태로 실행할 수 있다.
    """
    from src.core import crawler_engine

    소스 = _코드만(crawler_engine.CrawlerEngine.setup_driver)
    headless_줄 = [줄 for 줄 in 소스.splitlines() if "--headless" in 줄]

    assert headless_줄, "headless 처리 코드가 사라졌다"
    assert 'get("manual_login"' in 소스, "수동 로그인 여부를 확인하지 않는다(충돌 방어 없음)"


# ──────────────────────────────────────────────────────────────
# 4. 침묵 실패 금지 — 옵션은 켰는데 선택자가 빈 경우
# ──────────────────────────────────────────────────────────────
def test_페이지순회_선택자가_비면_사용자에게_알린다(tmp_path):
    """⛔ 회귀 방지: 조용히 1페이지에서 끝나 '왜 안 넘어가지?' 를 알 수 없었다."""
    e = _엔진(tmp_path, use_pagination=True, pagination_selector="")
    받은_메시지 = []

    결과 = e._go_to_next_page(callback=받은_메시지.append)

    assert 결과 is False
    assert 받은_메시지, "선택자가 비었는데 아무 안내도 하지 않는다"
    assert "선택자" in 받은_메시지[0]


def test_수집범위_선택자가_비면_사용자에게_알린다():
    """⛔ 회귀 방지: 영역 제한이 걸린 줄 알았는데 조용히 페이지 전체를 수집했다."""
    from src.ui import main_window

    소스 = _코드만(main_window.MainWindow.run_crawler)
    assert "scope_var.get() and not target_selector" in 소스.replace("  ", " ") or \
           "not target_selector" in 소스, "빈 선택자를 확인하지 않는다"


# ──────────────────────────────────────────────────────────────
# 5. 중지 반응성 — 모든 긴 대기가 중지에 반응해야 한다
# ──────────────────────────────────────────────────────────────
def test_모든_긴_대기는_중지에_반응한다():
    """
    ⛔ 회귀 방지: 딜레이 5단계에서 '다음 페이지' 대기가 7초까지 늘어나는데
       통째로 sleep 해서, 중지를 눌러도 그 시간만큼 계속 요청이 나갔다.
    """
    from src.core import crawler_engine

    소스 = _코드만(crawler_engine)
    통째_sleep = [줄.strip() for 줄 in 소스.splitlines()
                 if re.search(r"time\.sleep\(", 줄) and "0.1" not in 줄
                 and "min(chunk" not in 줄 and "time.sleep(1)" not in 줄]

    assert not 통째_sleep, f"중지에 반응하지 않는 대기가 남아 있다: {통째_sleep}"


def test_중지되면_대기_함수가_즉시_False를_돌려준다(tmp_path):
    import threading
    e = _엔진(tmp_path)
    stop = threading.Event()
    stop.set()

    시작 = __import__("time").monotonic()
    결과 = e._sleep_interruptible(5.0, stop)
    걸린시간 = __import__("time").monotonic() - 시작

    assert 결과 is False
    assert 걸린시간 < 0.5, f"중지 요청이 있는데 {걸린시간:.1f}초를 기다렸다"


# ──────────────────────────────────────────────────────────────
# 6. 보안 — 로그인 쿠키가 제3자 호스트로 새지 않는다
# ──────────────────────────────────────────────────────────────
def test_로그인_쿠키는_해당_도메인에만_전송된다(tmp_path):
    """
    ⛔ 회귀 방지: 예전에는 쿠키를 {이름:값} 으로만 넣어서 requests 가 '모든 호스트'에 보냈다.
       로그인 세션 쿠키가 외부 CDN·광고·추적 도메인까지 전송되는 개인정보 유출이었다.
    """
    cfg = ConfigManager(config_path=str(tmp_path / "config" / "settings.json"))
    dl = ImageDownloader(cfg)
    dl._set_cookies([
        {"name": "SESSION", "value": "secret", "domain": "members.example.com", "path": "/"},
    ])
    session = dl._get_session()

    보내는_쿠키 = session.cookies.get_dict(domain="members.example.com")
    assert 보내는_쿠키.get("SESSION") == "secret", "정작 필요한 도메인에는 보내야 한다"

    # 제3자 호스트로는 나가지 않아야 한다
    남의_도메인 = session.cookies.get_dict(domain="cdn.tracker.net")
    assert "SESSION" not in 남의_도메인, "로그인 쿠키가 제3자 도메인으로 새고 있다"


def test_쿠키_형식이_이상해도_다운로드가_멈추지_않는다(tmp_path):
    cfg = ConfigManager(config_path=str(tmp_path / "config" / "settings.json"))
    dl = ImageDownloader(cfg)
    dl._set_cookies([
        {"name": "GOOD", "value": "1", "domain": "a.com", "path": "/"},
        {"name": None, "value": None},          # 깨진 항목
        {"value": "이름없음"},                    # 이름 없음
    ])
    session = dl._get_session()
    assert session.cookies.get_dict(domain="a.com").get("GOOD") == "1"


# ──────────────────────────────────────────────────────────────
# 7. 폭주 방지 — 방문 페이지 상한과 로그 도배 방지
# ──────────────────────────────────────────────────────────────
def test_방문_페이지_상한이_설정되어_있다():
    """⛔ 깊이 2단계에서 링크가 수백 개면 몇 시간 동안 대상 서버에 요청이 계속 나갔다."""
    from src.core import crawler_engine

    assert MAX_PAGES_PER_CRAWL > 0
    소스 = _코드만(crawler_engine.CrawlerEngine.crawl)
    assert "MAX_PAGES_PER_CRAWL" in 소스, "상한을 선언만 하고 실제로 확인하지 않는다"


def test_스크롤_로그는_매번_찍지_않는다():
    """⛔ 회귀 방지: 스크롤 한 번마다 같은 문구를 찍어 로그가 같은 줄 수백 개로 도배됐다."""
    from src.core import crawler_engine

    assert SCROLL_LOG_INTERVAL > 1
    소스 = _코드만(crawler_engine.CrawlerEngine.auto_scroll)
    assert "SCROLL_LOG_INTERVAL" in 소스


# ──────────────────────────────────────────────────────────────
# 8. 재현성 — 같은 이미지는 언제 돌려도 같은 파일명
# ──────────────────────────────────────────────────────────────
def test_내장이미지_파일명은_실행마다_바뀌지_않는다(tmp_path):
    """
    ⛔ 회귀 방지: 파이썬 내장 hash() 는 실행마다 값이 달라진다(해시 시드 무작위화).
       같은 이미지를 다시 수집하면 파일명이 매번 바뀌어 결과를 비교할 수 없었다.
    """
    e = _엔진(tmp_path)
    주소 = "data:image/png;base64," + "Q" * 300

    이름 = e.get_filename_from_url(주소)
    assert 이름 == e.get_filename_from_url(주소), "같은 입력인데 이름이 다르다"
    assert 이름.startswith("embed_")

    # 다른 프로세스(=다른 해시 시드)에서도 같은 값이 나와야 한다
    import subprocess, sys, os
    코드 = (
        "import sys; sys.path.insert(0, r'%s');"
        "from src.core.crawler_engine import CrawlerEngine as C;"
        "e=C.__new__(C);print(e.get_filename_from_url(%r))" % (os.getcwd(), 주소)
    )
    env = dict(os.environ, PYTHONHASHSEED="12345")
    출력 = subprocess.run([sys.executable, "-c", 코드], capture_output=True, text=True, env=env)
    assert 출력.stdout.strip() == 이름, "다른 해시 시드에서 파일명이 달라졌다"


def test_건너뛴_이유를_사용자에게_알린다(tmp_path):
    """
    ⛔ 회귀 방지: '이미지 8개 발견 → 7개 저장' 처럼 숫자가 줄어도 이유를 알려주지 않아,
       사용자는 필터를 어떻게 고쳐야 할지 판단할 수 없었다(침묵 축소).
    """
    import io
    from PIL import Image as PILImage

    cfg = ConfigManager(config_path=str(tmp_path / "config" / "settings.json"))
    cfg.set_many({"min_width": 500, "min_height": 500})     # 일부러 전부 걸러지게 한다
    dl = ImageDownloader(cfg)

    buf = io.BytesIO()
    PILImage.new("RGB", (120, 120), (10, 10, 10)).save(buf, format="PNG")
    import base64
    작은_이미지 = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()

    받은_메시지 = []
    dl.process_images(
        [{"src": 작은_이미지, "filename": "x", "source_page": "https://a.com/p", "page_title": "T"}],
        base_result_dir=str(tmp_path / "results"),
        message_callback=받은_메시지.append,
    )

    assert 받은_메시지, "건너뛴 이유를 아무에게도 알리지 않았다"
    합친_메시지 = " ".join(받은_메시지)
    assert "최소 크기" in 합친_메시지, f"이유가 구체적이지 않다: {합친_메시지}"


def test_모두_정상_저장되면_불필요한_안내를_띄우지_않는다(tmp_path):
    """짝 테스트 — 문제가 없을 때 괜한 경고로 사용자를 불안하게 하지 않는다."""
    import io, base64
    from PIL import Image as PILImage

    cfg = ConfigManager(config_path=str(tmp_path / "config" / "settings.json"))
    cfg.set_many({"min_width": 0, "min_height": 0})
    dl = ImageDownloader(cfg)

    buf = io.BytesIO()
    PILImage.new("RGB", (120, 120), (10, 10, 10)).save(buf, format="PNG")
    이미지 = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()

    받은_메시지 = []
    dl.process_images(
        [{"src": 이미지, "filename": "x", "source_page": "https://a.com/p", "page_title": "T"}],
        base_result_dir=str(tmp_path / "results"),
        message_callback=받은_메시지.append,
    )
    assert not 받은_메시지, f"건너뛴 게 없는데 안내를 띄웠다: {받은_메시지}"


def test_확장자_목록이_한_곳에서만_정의된다():
    """⛔ 링크 제외 목록과 이미지 확장자 목록을 따로 적어 두면 한쪽만 갱신되어 어긋난다(DRY)."""
    for ext in KNOWN_IMG_EXTS:
        assert ext in NON_PAGE_EXTS, f"{ext} 가 링크 제외 목록에 없다 (이미지를 페이지로 오인한다)"


# ──────────────────────────────────────────────────────────────
# 9. 설정이 실제 동작으로 이어지는지 (연결 점검)
# ──────────────────────────────────────────────────────────────
@pytest.mark.parametrize("설정, 값, 기대_동작", [
    ({"respect_robots": False}, None, "robots 검사를 건너뛴다"),
])
def test_robots_설정이_실제로_반영된다(tmp_path, 설정, 값, 기대_동작):
    e = _엔진(tmp_path, **설정)
    # 네트워크에 나가지 않고도 True 를 돌려주어야 한다(설정이 꺼져 있으므로)
    assert e.is_allowed_by_robots("https://example.com/anything") is True


@pytest.mark.parametrize("설정값, 기대, 설명", [
    (0, 250, "0 은 '스크롤 0번' 이 아니라 '자동' 이다"),
    (-5, 250, "음수도 자동"),
    (None, 250, "값이 없어도 자동"),
    ("이상한값", 250, "숫자가 아니어도 자동"),
    (50, 50, "사용자가 정한 값은 그대로 쓴다"),
])
def test_스크롤_횟수_설정에서_0은_자동을_뜻한다(tmp_path, 설정값, 기대, 설명):
    """
    ⛔ 회귀 방지: max_scrolls 는 오래전부터 설정 파일에 있었지만 코드가 250 을 하드코딩해
       아무 효과가 없는 '죽은 설정' 이었다. 그런데 실제 사용자 파일에는 0 이 들어 있었다.
       이 값을 그대로 '0번 스크롤' 로 읽으면 지연로딩 이미지가 통째로 유실된다.
    """
    e = _엔진(tmp_path, max_scrolls=설정값)
    assert e._max_scrolls() == 기대, 설명


def test_설정파일에_죽은_키가_남아있지_않다():
    """
    ⛔ 회귀 방지: 코드가 읽지 않는 키가 설정 파일에 있으면, 사용자가 그것을 고치고
       '왜 안 되지?' 하게 된다(사용자 입장에서는 죽은 설정). allowed_extensions 는
       ext_jpg/ext_png/... 체크박스와 중복이어서 제거했다.
    """
    import json
    import re
    from src.utils import config_manager

    설정파일 = json.load(open("config/settings.json", encoding="utf-8"))
    소스 = open(config_manager.__file__, encoding="utf-8").read()
    블록 = 소스.split("self.default_config = {", 1)[1].split("\n        }", 1)[0]
    아는_키 = set(re.findall(r'"([a-z_0-9]+)":', 블록))

    모르는_키 = set(설정파일) - 아는_키
    assert not 모르는_키, f"코드가 읽지 않는 키가 설정 파일에 남아 있다: {sorted(모르는_키)}"


def test_페이지_로딩_대기시간_하한이_지켜진다(tmp_path):
    e = _엔진(tmp_path, timeout=1)
    assert e._page_load_timeout() == MIN_PAGE_LOAD_TIMEOUT


def test_제외키워드는_호스트명에_적용되지_않는다(tmp_path):
    """⛔ 회귀 방지: 'banner' 를 제외 키워드로 두면 bannershop.co.kr 이미지가 전멸했다."""
    e = _엔진(tmp_path, exclude_keywords="banner")

    assert e.is_excluded("https://bannershop.co.kr/img/photo.jpg") is False
    assert e.is_excluded("https://shop.co.kr/img/banner1.jpg") is True
