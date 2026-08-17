"""[platform-bot] 외부 사이트 접근 '속도 안전장치' 점검.

크롤러가 빨라지는 것은 기능 개선이 아니라 위험 증가다 — IP 차단, 법적 분쟁,
대상 서버 부하(전역수칙 9). 그래서 '딜레이가 0 이 되는 경로가 없는지',
'robots.txt 준수가 기본값인지'를 빌드마다 강제로 확인한다.
"""
import threading
import time

import pytest

from src.core.crawler_engine import CrawlerEngine
from src.utils.config_manager import ConfigManager, delay_bounds


@pytest.fixture
def engine(tmp_path):
    return CrawlerEngine(ConfigManager(config_path=str(tmp_path / "config" / "settings.json")))


# ──────────────────────────────────────────────────────────
# 안전 기본값
# ──────────────────────────────────────────────────────────
def test_robots_준수가_기본값으로_켜져_있다(engine):
    """⛔ 준법 기본값. 이게 False 로 출고되면 사용자가 모르는 채 규약을 위반한다."""
    assert engine.config.get("respect_robots") is True


def test_딜레이_기본값이_0이_아니다(engine):
    assert engine.config.get("random_delay_min") >= 1.0
    assert engine.config.get("random_delay_max") > engine.config.get("random_delay_min")


@pytest.mark.parametrize("delay_level", [1, 2, 3, 4, 5])
def test_어떤_딜레이_단계에서도_요청_간격이_0이_되지_않는다(delay_level):
    """UI 슬라이더(1~5) 전 구간 전수 검사.

    ⛔ UI와 '같은 함수'(delay_bounds)를 호출한다 — 공식을 여기에 다시 적으면
       두 벌이 되어, 화면 표시와 실제 동작이 어긋나도 테스트가 못 잡는다.
    """
    최소, 최대 = delay_bounds(delay_level)

    assert 최소 > 0, f"단계 {delay_level} 에서 딜레이가 0 이 된다(차단 위험)"
    assert 최대 > 최소, "최대가 최소보다 커야 무작위성이 생긴다"
    assert 최대 >= 1.5, f"단계 {delay_level} 의 최대 대기가 너무 짧다"


@pytest.mark.parametrize("비정상_입력", [0, -5, 0.4])
def test_딜레이_단계가_비정상이어도_0초_요청이_되지_않는다(비정상_입력):
    """슬라이더 값이 어떤 이유로 0 이하로 들어와도 '지연 없는 폭주'가 되면 안 된다."""
    최소, 최대 = delay_bounds(비정상_입력)
    assert 최소 >= 0.5, f"입력 {비정상_입력} 에서 딜레이가 {최소}초로 떨어졌다"
    assert 최대 >= 1.5


def test_페이지_순회에_상한이_있다(engine):
    """⛔ 상한이 없으면 '다음 페이지'를 무한히 눌러 대상 서버를 두드린다."""
    상한 = int(engine.config.get("max_pagination_pages"))
    assert 0 < 상한 <= 100


def test_이미지_용량_상한이_있다(engine):
    """상한이 없으면 거대 파일 하나로 메모리가 폭주한다."""
    assert 0 < int(engine.config.get("max_image_mb")) <= 100


# ──────────────────────────────────────────────────────────
# 중지 반응성 — '멈춰달라'는 요청은 즉시 들어야 한다
# ──────────────────────────────────────────────────────────
def test_스크롤_중_중지신호에_즉시_반응한다(engine):
    """중지를 눌렀는데 몇 분씩 스크롤이 계속되면 사용자는 프로그램이 멈춘 줄 안다."""
    stop = threading.Event()
    실행된_스크립트 = []

    class 가짜드라이버:
        def execute_script(self, script, *args):
            실행된_스크립트.append(script)
            stop.set()                     # 첫 스크롤 직후 중지 요청
            return 10000                   # scrollHeight 등

    engine.driver = 가짜드라이버()
    engine.config.set_many({"random_delay_min": 5.0, "random_delay_max": 5.0})

    시작 = time.monotonic()
    engine.auto_scroll(stop_event=stop)
    걸린시간 = time.monotonic() - 시작

    assert 걸린시간 < 2.0, f"중지 후 {걸린시간:.1f}초나 더 스크롤했다(딜레이 5초를 통째로 기다린 것)"
    assert len(실행된_스크립트) <= 2, "중지 후에도 스크롤을 계속했다"


def test_수동로그인_대기중_중지가_먹힌다(engine):
    """로그인 대기(기본 30초) 동안 중지를 눌러도 반응해야 한다."""
    stop = threading.Event()
    stop.set()

    class 가짜드라이버:
        def get(self, url):
            pass

        def get_cookies(self):
            return []

        def quit(self):
            pass

        def set_page_load_timeout(self, t):
            pass

    engine.driver = 가짜드라이버()
    engine.config.set_many({"manual_login": True, "login_wait": 30, "respect_robots": False})

    시작 = time.monotonic()
    결과 = engine.crawl("https://example.invalid", stop_event=stop)
    걸린시간 = time.monotonic() - 시작

    assert 결과 == []
    assert 걸린시간 < 3.0, f"중지 상태인데 {걸린시간:.1f}초를 대기했다"


# ──────────────────────────────────────────────────────────
# robots.txt 판정
# ──────────────────────────────────────────────────────────
def test_robots_조회가_실패하면_과잉차단하지_않는다(engine):
    """robots.txt 가 없는 사이트(404)를 '금지'로 해석하면 정상 수집이 전부 막힌다."""
    engine.config.set_many({"respect_robots": True})
    engine._robots_cache["https://no-robots.invalid"] = None
    assert engine.is_allowed_by_robots("https://no-robots.invalid/page") is True


def test_robots_준수를_끄면_검사_자체를_하지_않는다(engine):
    """사용자가 책임 고지에 동의하고 끈 경우 — 네트워크 조회조차 하지 않아야 빠르다."""
    engine.config.set_many({"respect_robots": False})
    assert engine.is_allowed_by_robots("https://any.invalid/x") is True
    assert engine._robots_cache == {}, "꺼져 있는데 robots.txt 를 조회했다"
