"""회귀 테스트 — v1.0.16 에서 고친 '조용히 이미지를 놓치는' 버그 5건.

이 버그들의 공통점은 **에러가 안 난다**는 것이다. 프로그램은 정상 종료되고 로그도 깨끗한데
결과만 비어 있어서, 사용자는 "사이트가 원래 그런가 보다"라고 넘어간다.
그래서 자동 테스트로 못 박아 둔다 — 여기가 깨지면 빌드가 멈춘다.

배경: troubleshooting/2026-08-17_전체점검_수집손실_버그.md
"""
import pytest
from bs4 import BeautifulSoup

from src.core.crawler_engine import CrawlerEngine
from src.utils.config_manager import ConfigManager


@pytest.fixture
def engine(tmp_path):
    return CrawlerEngine(ConfigManager(config_path=str(tmp_path / "config" / "settings.json")))


# ──────────────────────────────────────────────────────────
# ① 지연로딩(lazy-load) — 투명 플레이스홀더 대신 '진짜' 주소를 골라야 한다
# ──────────────────────────────────────────────────────────
투명_1x1 = "data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7"


@pytest.mark.parametrize("html, 기대주소, 설명", [
    (f'<img src="{투명_1x1}" data-src="/real.jpg">', "/real.jpg", "data-src"),
    (f'<img src="{투명_1x1}" data-original="/real.jpg">', "/real.jpg", "data-original"),
    (f'<img src="{투명_1x1}" data-lazy-src="/real.jpg">', "/real.jpg", "data-lazy-src"),
    (f'<img src="{투명_1x1}" data-echo="/real.jpg">', "/real.jpg", "data-echo"),
    (f'<img src="{투명_1x1}" data-actualsrc="/real.jpg">', "/real.jpg", "data-actualsrc"),
    (f'<img src="{투명_1x1}" data-hi-res-src="/real.jpg">', "/real.jpg", "data-hi-res-src"),
    ('<img src="/placeholder.png" data-src="/real.jpg">', "/real.jpg", "이름이 placeholder"),
    ('<img src="/img/loading.gif" data-src="/real.jpg">', "/real.jpg", "이름이 loading"),
    ('<img src="/normal.jpg">', "/normal.jpg", "지연로딩 아닌 평범한 이미지"),
])
def test_지연로딩_속성에서_진짜_주소를_고른다(engine, html, 기대주소, 설명):
    img = BeautifulSoup(html, "html.parser").find("img")
    assert engine.pick_image_src(img) == 기대주소, f"[{설명}] 플레이스홀더를 진짜 이미지로 착각했다"


def test_srcset_에서_가장_큰_해상도를_고른다(engine):
    """작은 썸네일을 받아오면 '수집은 됐는데 쓸 수 없는' 결과가 된다."""
    img = BeautifulSoup(
        '<img srcset="s.jpg 400w, l.jpg 1600w, m.jpg 800w" src="tiny.jpg">', "html.parser"
    ).find("img")
    assert engine.pick_image_src(img) == "l.jpg"


@pytest.mark.parametrize("srcset, 기대", [
    ("a.jpg 400w, b.jpg 1200w", "b.jpg"),
    ("a.jpg 1x, b.jpg 3x", "b.jpg"),
    ("only.jpg", "only.jpg"),                 # 디스크립터 없음
    ("a.jpg 400w, b.jpg", "a.jpg"),           # 섞여 있음 — 점수 있는 쪽
])
def test_srcset_파싱_경계값(engine, srcset, 기대):
    assert engine.pick_from_srcset(srcset) == 기대


def test_모든_후보가_플레이스홀더처럼_보여도_포기하지_않는다(engine):
    """⛔ 오탐 대비. '플레이스홀더 같다'고 전부 버리면 정상 이미지까지 놓친다."""
    img = BeautifulSoup(f'<img src="{투명_1x1}">', "html.parser").find("img")
    assert engine.pick_image_src(img) is not None


# ──────────────────────────────────────────────────────────
# ② Base64 내장 이미지 — 파일명이 윈도우 경로 한계를 넘지 않아야 한다
# ──────────────────────────────────────────────────────────
def test_data_uri_파일명이_짧게_생성된다(engine):
    """⛔ 예전에는 base64 본문에서 파일명을 뽑아 247자가 되어, 윈도우 260자 한계를
    넘겨 저장이 통째로 실패했다(로그에는 아무것도 안 남았다)."""
    거대_data_uri = "data:image/png;base64," + "A" * 50000
    filename = engine.get_filename_from_url(거대_data_uri)

    assert len(filename) <= 32, f"파일명이 {len(filename)}자 — 경로 한계를 넘길 수 있다"
    assert filename.startswith("embed_")


def test_같은_data_uri_는_같은_파일명을_돌려준다(engine):
    uri = "data:image/png;base64," + "B" * 2000
    assert engine.get_filename_from_url(uri) == engine.get_filename_from_url(uri)


@pytest.mark.parametrize("url", [
    "https://x.com/사진/한글이름.jpg",           # ASCII 로 지우면 빈 문자열이 되는 경우
    "https://x.com/" + "a" * 300 + ".jpg",      # 아주 긴 파일명
    "https://x.com/",                            # 파일명 없음
    "https://x.com/photo.jpg?x=1&y=2",
])
def test_어떤_주소에서도_사용가능한_파일명이_나온다(engine, url):
    stem = engine.get_filename_from_url(url)
    assert stem, "파일명이 비면 저장이 실패한다"
    assert len(stem) <= 60
    assert not set(stem) & set('<>:"|?*\\/'), f"파일명에 금지문자가 있다: {stem}"
    assert "." not in stem, "확장자는 PIL 판별 후에 붙여야 한다(PNG가 .jpg로 저장되는 문제 방지)"


# ──────────────────────────────────────────────────────────
# ③ 링크 정규화 — 같은 페이지를 수십 번 재방문하지 않아야 한다
# ──────────────────────────────────────────────────────────
def test_앵커만_다른_링크는_같은_페이지로_취급한다(engine):
    """⛔ 예전에는 #a, #b 를 서로 다른 페이지로 봐서 같은 페이지를 수십 번 열었다."""
    a = engine.normalize_link("https://x.com/page#section-a")
    b = engine.normalize_link("https://x.com/page#section-b")
    assert a == b == "https://x.com/page"


@pytest.mark.parametrize("링크", [
    "https://x.com/manual.pdf",
    "https://x.com/data.zip",
    "https://x.com/photo.jpg",       # 이미지는 '페이지'가 아니다
    "https://x.com/style.css",
    "https://x.com/app.js",
    "mailto:a@b.com",
    "javascript:void(0)",
    "tel:010-1234-5678",
])
def test_페이지가_아닌_링크는_큐에_넣지_않는다(engine, 링크):
    assert engine.normalize_link(링크) is None


def test_쿼리스트링은_보존한다(engine):
    """게시판은 ?page=2 로 페이지를 나누므로 쿼리를 지우면 목록을 못 넘어간다."""
    assert engine.normalize_link("https://x.com/list?page=2") == "https://x.com/list?page=2"


def test_끝슬래시_유무를_같은_페이지로_통일한다(engine):
    assert engine.normalize_link("https://x.com") == engine.normalize_link("https://x.com/")


# ──────────────────────────────────────────────────────────
# ④ 제외 키워드 — 호스트명 때문에 사이트 전체가 걸러지면 안 된다
# ──────────────────────────────────────────────────────────
def test_호스트명은_제외키워드_검사에서_빠진다(engine):
    """⛔ 'banner' 를 제외 키워드로 두면 bannershop.co.kr 의 이미지가 전멸했다."""
    engine.config.set_many({"exclude_keywords": "banner, logo"})
    assert engine.is_excluded("https://bannershop.co.kr/goods/photo.jpg") is False
    assert engine.is_excluded("https://shop.co.kr/banner/top.jpg") is True


def test_제외키워드는_경로와_쿼리_모두_검사한다(engine):
    engine.config.set_many({"exclude_keywords": "tracker"})
    assert engine.is_excluded("https://x.com/img.jpg?src=tracker") is True


def test_제외키워드가_비어있으면_아무것도_걸러지지_않는다(engine):
    engine.config.set_many({"exclude_keywords": ""})
    assert engine.is_excluded("https://x.com/banner/logo/icon.jpg") is False


# ──────────────────────────────────────────────────────────
# ⑤ 확장자 화이트리스트 — '허용 목록이 비었다' = '아무것도 허용 안 함'
# ──────────────────────────────────────────────────────────
def test_확장자를_모두_해제하면_전부_제외된다(engine):
    """⛔ 예전에는 `if valid_exts:` 가드 때문에 검사를 건너뛰어, 다 해제하면
    오히려 '전부 수집'되는 정반대 동작이었다."""
    engine.config.set_many({"ext_jpg": False, "ext_png": False, "ext_webp": False, "ext_gif": False})

    for url in ["https://x.com/a.jpg", "https://x.com/a.png", "https://x.com/a.webp", "https://x.com/a.gif"]:
        assert engine.is_excluded(url) is True, f"{url} 이 허용됐다 — 화이트리스트가 무력화됐다"


@pytest.mark.parametrize("설정, 허용_url, 차단_url", [
    ({"ext_jpg": True, "ext_png": False}, "https://x.com/a.jpg", "https://x.com/a.png"),
    ({"ext_jpg": False, "ext_png": True}, "https://x.com/a.png", "https://x.com/a.jpg"),
    ({"ext_webp": True, "ext_jpg": False}, "https://x.com/a.webp", "https://x.com/a.jpg"),
])
def test_확장자_조합별로_정확히_동작한다(engine, 설정, 허용_url, 차단_url):
    기본 = {"ext_jpg": False, "ext_png": False, "ext_webp": False, "ext_gif": False,
            "exclude_keywords": ""}
    기본.update(설정)
    engine.config.set_many(기본)

    assert engine.is_excluded(허용_url) is False
    assert engine.is_excluded(차단_url) is True


def test_확장자가_없는_주소는_통과시킨다(engine):
    """/image?id=123 처럼 확장자가 없는 주소도 이미지일 수 있다 — PIL 이 나중에 판별한다."""
    engine.config.set_many({"exclude_keywords": ""})
    assert engine.is_excluded("https://x.com/image?id=123") is False


def test_base64_수집_여부는_설정으로_제어된다(engine):
    engine.config.set_many({"ext_allow_base64": True})
    assert engine.is_excluded(투명_1x1) is False

    engine.config.set_many({"ext_allow_base64": False})
    assert engine.is_excluded(투명_1x1) is True


# ──────────────────────────────────────────────────────────
# 중복 제거 — 같은 이미지는 한 번만, 다른 이미지는 놓치지 않고
# ──────────────────────────────────────────────────────────
def test_쿼리스트링만_다른_같은_이미지는_한_번만_담는다(engine):
    a = engine.dedup_key("https://x.com/photo.jpg?v=1")
    b = engine.dedup_key("https://x.com/photo.jpg?v=2")
    assert a == b


def test_경로가_다른_이미지는_구분한다(engine):
    a = engine.dedup_key("https://x.com/a/photo.jpg")
    b = engine.dedup_key("https://x.com/b/photo.jpg")
    assert a != b


def test_필수포함_키워드가_비어있으면_모두_통과시킨다(engine):
    """⛔ 이 기능은 '미사용'이 기본이다. 빈 값에서 걸러버리면 수집 결과가 0 이 된다."""
    engine.config.set_many({"include_keywords": ""})
    assert engine.has_include_keywords(["아무 설명"]) is True
    assert engine.has_include_keywords([None, ""]) is True


def test_필수포함_키워드는_하나만_맞아도_통과한다(engine):
    engine.config.set_many({"include_keywords": "풍경, 여행"})
    assert engine.has_include_keywords(["가을 풍경 사진"]) is True
    assert engine.has_include_keywords(["제품 상세"]) is False
