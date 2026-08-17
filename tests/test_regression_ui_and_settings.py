"""UI 일관성 · 설정 점검(2026-08-17)에서 고친 결함들의 회귀 방지 테스트.

이번 점검에서 드러난 공통 패턴은 두 가지다.
  ① '표시 = 동작' 불일치 — 화면에 보이는 설정이 실제로는 안 쓰이거나 반쪽만 쓰인다.
  ② 침묵 축소 — 잘못된 입력·불가능한 상황을 조용히 기본값으로 바꿔 사용자가 알 수 없다.
아래 테스트는 그 두 가지가 되살아나는 것을 막는다.
"""
import ast
import base64
import inspect
import io
import json
import re
import textwrap

import pytest
from PIL import Image

from src.core.image_downloader import ImageDownloader
from src.ui.main_window import MainWindow, DEPTH_LABELS, depth_label_for, depth_value_from
from src.utils.config_manager import ConfigManager, allowed_extensions


# ──────────────────────────────────────────────────────────────
# 도우미
# ──────────────────────────────────────────────────────────────
def _코드만(모듈_또는_함수):
    """
    주석과 docstring 을 걷어낸 '실제 실행되는 코드'만 돌려준다.

    ⛔ 이 도우미가 필요한 이유: 이 프로젝트는 전역수칙에 따라 ⛔ 주석에 '예전에 이렇게
       잘못했었다'는 옛 코드를 그대로 인용해 둔다. 소스 전체를 문자열로 검색하면
       그 인용문까지 걸려서, 고쳐 놓은 코드를 '아직 안 고쳤다'고 잘못 판정한다.
    """
    # ⛔ cleandoc 이 아니라 dedent 를 쓴다. cleandoc 은 첫 줄만 다르게 처리해서
    #    메서드 소스의 들여쓰기가 깨진다(IndentationError).
    소스 = textwrap.dedent(inspect.getsource(모듈_또는_함수))
    tree = ast.parse(소스)

    제외줄 = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            if ast.get_docstring(node, clean=False) is not None:
                첫_문장 = node.body[0]
                제외줄.update(range(첫_문장.lineno, (첫_문장.end_lineno or 첫_문장.lineno) + 1))

    남긴_줄 = []
    for 번호, 줄 in enumerate(소스.splitlines(), start=1):
        if 번호 in 제외줄 or 줄.strip().startswith("#"):
            continue
        남긴_줄.append(줄)
    return "\n".join(남긴_줄)


def _설정(tmp_path, **값):
    """임시 폴더에 설정을 만들어 ConfigManager 를 돌려준다."""
    cfg = ConfigManager(config_path=str(tmp_path / "config" / "settings.json"))
    if 값:
        cfg.set_many(값)
    return cfg


def _이미지_데이터URI(포맷, 크기=(120, 120)):
    """네트워크 없이 검사할 수 있도록 실제 이미지를 data URI 로 만든다."""
    buf = io.BytesIO()
    Image.new("RGB", 크기, (10, 120, 200)).save(buf, format=포맷)
    b64 = base64.b64encode(buf.getvalue()).decode()
    mime = 포맷.lower()
    return f"data:image/{mime};base64,{b64}"


class _가짜변수:
    """tkinter StringVar 대신 쓰는 최소 구현 (get/set 만 필요하다)."""
    def __init__(self, value):
        self._v = value

    def get(self):
        return self._v

    def set(self, value):
        self._v = value


class _가짜창:
    """MainWindow 의 순수 로직만 떼어 검사하기 위한 최소 스텁."""
    def __init__(self, config_manager):
        self.config_manager = config_manager
        self.logs = []

    def append_log(self, message):
        self.logs.append(message)


# ──────────────────────────────────────────────────────────────
# 1. 허용 확장자 목록 — 크롤러와 다운로더가 '같은 한 곳'을 본다
# ──────────────────────────────────────────────────────────────
@pytest.mark.parametrize("켠_것, 기대", [
    (dict(ext_jpg=True, ext_png=False, ext_webp=False, ext_gif=False), ('.jpg', '.jpeg')),
    (dict(ext_jpg=False, ext_png=True, ext_webp=False, ext_gif=False), ('.png',)),
    (dict(ext_jpg=False, ext_png=False, ext_webp=True, ext_gif=False), ('.webp',)),
    (dict(ext_jpg=False, ext_png=False, ext_webp=False, ext_gif=True), ('.gif',)),
    (dict(ext_jpg=True, ext_png=True, ext_webp=True, ext_gif=True),
     ('.jpg', '.jpeg', '.png', '.webp', '.gif')),
    # 전부 해제 = '아무것도 허용하지 않음' (화이트리스트의 정의)
    (dict(ext_jpg=False, ext_png=False, ext_webp=False, ext_gif=False), ()),
])
def test_허용_확장자_목록은_체크한_것만_돌려준다(tmp_path, 켠_것, 기대):
    cfg = _설정(tmp_path, **켠_것)
    assert allowed_extensions(cfg) == 기대


def test_확장자_목록은_한_곳에서만_만들어진다():
    """⛔ 회귀 방지: 엔진과 다운로더가 각자 목록을 만들면 두 벌이 어긋난다."""
    import inspect
    from src.core import crawler_engine, image_downloader

    for 모듈 in (crawler_engine, image_downloader):
        소스 = inspect.getsource(모듈)
        assert "allowed_extensions" in 소스, f"{모듈.__name__} 이 공용 함수를 쓰지 않는다"
        # 목록을 직접 조립하던 옛 코드가 되살아나지 않았는지 확인
        assert 'valid_exts.append' not in 소스, f"{모듈.__name__} 에서 확장자 목록을 다시 조립하고 있다"


# ──────────────────────────────────────────────────────────────
# 2. 확장자 필터는 '실제 파일 포맷'에도 적용된다 (핵심 회귀)
# ──────────────────────────────────────────────────────────────
def test_확장자를_끄면_주소에_확장자가_없어도_저장되지_않는다(tmp_path):
    """
    ⛔ 회귀 방지: 예전에는 크롤러가 '주소 끝의 확장자'만 검사했다.
       그래서 /photo?id=1 처럼 확장자 없는 주소는 필터를 통과한 뒤,
       내려받아 보니 GIF 인데도 GIF 체크를 껐는지와 무관하게 .gif 로 저장됐다.
    """
    cfg = _설정(tmp_path, ext_gif=False, min_width=0, min_height=0)
    dl = ImageDownloader(cfg)
    img = {"src": _이미지_데이터URI("GIF"), "filename": "no_ext", "source_page": "https://a.com"}

    결과 = dl._download_single_image(img, 0, str(tmp_path), None)

    assert 결과 is None, "GIF 를 껐으면 실제 포맷이 GIF 인 파일은 저장되지 않아야 한다"
    assert not list(tmp_path.glob("*.gif")), "파일이 실제로 남아 있으면 안 된다"


def test_확장자를_켜면_같은_이미지가_정상_저장된다(tmp_path):
    """위 테스트가 '필터가 과하게 막는 것'이 아님을 증명한다 (짝 테스트)."""
    cfg = _설정(tmp_path, ext_gif=True, min_width=0, min_height=0)
    dl = ImageDownloader(cfg)
    img = {"src": _이미지_데이터URI("GIF"), "filename": "no_ext", "source_page": "https://a.com"}

    결과 = dl._download_single_image(img, 0, str(tmp_path), None)

    assert 결과 is not None
    assert 결과["saved_filename"].endswith(".gif")


# ──────────────────────────────────────────────────────────────
# 3. 죽은 설정 되살리기 — timeout 이 실제로 반영된다
# ──────────────────────────────────────────────────────────────
@pytest.mark.parametrize("설정값, 기대", [
    (60, 60),      # 사용자가 늘리면 늘어나야 한다
    (30, 30),      # 기본값
    (1, 5),        # 너무 짧으면 하한(5초)으로 보정
    (0, 5),
    ("이상한값", 30),  # 숫자가 아니면 기본값
])
def test_페이지_로딩_대기시간은_설정을_실제로_사용한다(tmp_path, 설정값, 기대):
    """
    ⛔ 회귀 방지: 예전에는 set_page_load_timeout(30) 이 두 곳에 하드코딩되어 있고
       settings.json 의 timeout 은 아무도 읽지 않는 '죽은 설정'이었다.
    """
    from src.core.crawler_engine import CrawlerEngine

    cfg = _설정(tmp_path, timeout=설정값)
    engine = CrawlerEngine.__new__(CrawlerEngine)   # 크롬을 띄우지 않고 계산만 검사
    engine.config = cfg

    assert engine._page_load_timeout() == 기대


def test_모든_대기시간_설정_지점이_공용_함수를_쓴다():
    """⛔ 회귀 방지: 한 곳만 고치고 다른 곳에 30 이 남으면 다시 두 벌이 된다."""
    from src.core import crawler_engine

    호출들 = [줄.strip() for 줄 in _코드만(crawler_engine).splitlines()
              if "set_page_load_timeout(" in 줄]

    assert 호출들, "대기시간을 설정하는 코드가 사라졌다"
    for 호출 in 호출들:
        assert "self._page_load_timeout()" in 호출, f"하드코딩된 값이 남아 있다: {호출}"
        assert not re.search(r"set_page_load_timeout\(\s*\d", 호출), f"숫자를 직접 넣고 있다: {호출}"


def test_유저에이전트_로테이션_설정이_실제로_읽힌다():
    """⛔ 회귀 방지: 이 설정도 아무도 읽지 않아 항상 켜진 상태로 동작했다."""
    from src.core import crawler_engine

    assert 'get("user_agent_rotation"' in _코드만(crawler_engine)


# ──────────────────────────────────────────────────────────────
# 4. 화면 문구 ↔ 저장값 (크롤링 깊이)
# ──────────────────────────────────────────────────────────────
@pytest.mark.parametrize("저장값, 기대_문구", [
    (1, DEPTH_LABELS[0]), (2, DEPTH_LABELS[1]), (3, DEPTH_LABELS[1]),
    ("2", DEPTH_LABELS[1]), (None, DEPTH_LABELS[0]), ("깨진값", DEPTH_LABELS[0]),
])
def test_깊이_설정은_어떤_저장값에도_안전하게_표시된다(저장값, 기대_문구):
    assert depth_label_for(저장값) == 기대_문구


@pytest.mark.parametrize("문구", DEPTH_LABELS)
def test_깊이_문구와_숫자는_왕복해도_같다(문구):
    """⛔ 화면 문구를 그대로 저장하면 문구만 다듬어도 설정이 초기화된다. 숫자로 저장한다."""
    assert depth_label_for(depth_value_from(문구)) == 문구


def test_깊이_판정에_문자열_비교가_남아있지_않다():
    """⛔ 회귀 방지: 예전에는 run_crawler 가 "2단계" 라는 글자를 직접 찾아 비교했다.
    화면 문구를 다듬는 순간 깊이 설정이 조용히 1단계로 되돌아간다."""
    from src.ui import main_window

    실행부 = _코드만(main_window.MainWindow.run_crawler)

    assert "depth_value_from(" in 실행부, "변환은 공용 함수를 거쳐야 한다"
    assert "2단계" not in 실행부, "화면 문구를 코드에서 직접 비교하고 있다"


# ──────────────────────────────────────────────────────────────
# 5. 침묵 축소 금지 — 잘못된 숫자 입력
# ──────────────────────────────────────────────────────────────
@pytest.mark.parametrize("잘못된_입력", ["abc", "", "-5", "10.5", " ", "100px"])
def test_숫자칸에_잘못된_값을_넣으면_조용히_0이_되지_않는다(tmp_path, 잘못된_입력):
    """
    ⛔ 회귀 방지: 예전에는 `int(v) if v.isdigit() else 0` 이라서
       최소 이미지 크기에 오타가 나면 말없이 0 이 되어 필터가 통째로 꺼졌다.
       사용자는 1×1 추적 픽셀까지 수집되는 이유를 알 수 없었다.
    """
    cfg = _설정(tmp_path, min_width=250)
    창 = _가짜창(cfg)
    변수 = _가짜변수(잘못된_입력)

    결과 = MainWindow._read_int_field(창, 변수, "최소 이미지 크기(가로)", "min_width")

    assert 결과 == 250, "직전에 저장된 값이 유지되어야 한다"
    assert 변수.get() == "250", "입력칸도 실제 적용값으로 되돌려 표시=동작을 맞춰야 한다"
    assert 창.logs, "사용자에게 반드시 알려야 한다(침묵 금지)"
    assert "무시" in 창.logs[0]


@pytest.mark.parametrize("정상_입력, 기대", [("0", 0), ("1", 1), ("300", 300)])
def test_정상적인_숫자는_그대로_반영된다(tmp_path, 정상_입력, 기대):
    cfg = _설정(tmp_path, min_width=250)
    창 = _가짜창(cfg)
    결과 = MainWindow._read_int_field(창, _가짜변수(정상_입력), "최소 크기", "min_width")

    assert 결과 == 기대
    assert not 창.logs, "정상 입력에는 경고를 띄우지 않아야 한다"


# ──────────────────────────────────────────────────────────────
# 6. 이어받기 기록 — 원자적 저장과 보존
# ──────────────────────────────────────────────────────────────
def test_기록_저장이_실패해도_기존_기록이_깨지지_않는다(tmp_path, monkeypatch):
    """
    ⛔ 회귀 방지: 원본에 직접 쓰다가 중간에 죽으면 JSON 이 반쪽만 남아
       기록을 못 읽고 수백 MB 를 다시 받았다. 임시 파일 → os.replace 라야 안전하다.
    """
    cfg = _설정(tmp_path)
    dl = ImageDownloader(cfg)
    경로 = str(tmp_path / "history.json")
    dl._save_history(경로, {"https://a.com/1.jpg"})

    # 쓰는 도중 강제 종료된 상황을 재현
    import src.core.image_downloader as mod
    def _터짐(*a, **k):
        raise OSError("디스크 꽉 찼음")
    monkeypatch.setattr(mod.json, "dump", _터짐)

    dl._save_history(경로, {"https://a.com/2.jpg"})   # 실패해야 한다

    남은_기록 = json.loads(open(경로, encoding="utf-8").read())
    assert 남은_기록 == ["https://a.com/1.jpg"], "실패했는데 기존 기록이 사라지거나 깨졌다"


def test_기록_저장후_임시파일이_남지_않는다(tmp_path):
    cfg = _설정(tmp_path)
    dl = ImageDownloader(cfg)
    경로 = str(tmp_path / "history.json")
    dl._save_history(경로, {"https://a.com/1.jpg"})

    assert not list(tmp_path.glob("*.tmp")), "임시 파일이 그대로 남으면 폴더가 지저분해진다"


def test_이어받기를_꺼도_기존_기록이_지워지지_않는다(tmp_path):
    """
    ⛔ 회귀 방지: 예전에는 이어받기가 꺼져 있으면 빈 기록으로 시작하고 저장을 건너뛰었다.
       '건너뛸지 말지'만 옵션이어야 하고, 무엇을 받았는지는 항상 남겨야 한다.
    """
    cfg = _설정(tmp_path, use_resume=False, min_width=0, min_height=0)
    dl = ImageDownloader(cfg)
    결과폴더 = str(tmp_path / "results")

    기록경로 = ImageDownloader.get_history_path(결과폴더, "https://a.com/page")
    dl._save_history(기록경로, {"https://a.com/old.jpg"})

    images = [{
        "src": _이미지_데이터URI("PNG"),
        "filename": "new",
        "source_page": "https://a.com/page",
        "page_title": "테스트",
    }]
    dl.process_images(images, base_result_dir=결과폴더)

    기록 = set(json.loads(open(기록경로, encoding="utf-8").read()))
    assert "https://a.com/old.jpg" in 기록, "이어받기를 껐다고 기존 기록을 잃어선 안 된다"
    assert len(기록) == 2, "이번에 받은 것도 기록에 남아야 한다"


def test_이어받기를_끄면_이미_받은_것도_다시_받는다(tmp_path):
    """옵션의 본래 목적(처음부터 다시 받기)이 동작하는지 — 삭제한 버튼의 대체 경로다."""
    cfg = _설정(tmp_path, use_resume=False, min_width=0, min_height=0)
    dl = ImageDownloader(cfg)
    결과폴더 = str(tmp_path / "results")
    주소 = _이미지_데이터URI("PNG")

    기록경로 = ImageDownloader.get_history_path(결과폴더, "https://a.com/page")
    dl._save_history(기록경로, {주소})    # 이미 받은 것으로 기록해 둔다

    images = [{"src": 주소, "filename": "again", "source_page": "https://a.com/page",
               "page_title": "테스트"}]
    저장폴더 = dl.process_images(images, base_result_dir=결과폴더)

    assert 저장폴더 is not None, "이어받기를 껐으면 기록에 있어도 다시 받아야 한다"


def test_이어받기를_켜면_이미_받은_것은_건너뛴다(tmp_path):
    """짝 테스트 — 위 동작이 '이어받기 기능 자체를 깨뜨린 것'이 아님을 증명한다."""
    cfg = _설정(tmp_path, use_resume=True, min_width=0, min_height=0)
    dl = ImageDownloader(cfg)
    결과폴더 = str(tmp_path / "results")
    주소 = _이미지_데이터URI("PNG")

    기록경로 = ImageDownloader.get_history_path(결과폴더, "https://a.com/page")
    dl._save_history(기록경로, {주소})

    images = [{"src": 주소, "filename": "again", "source_page": "https://a.com/page",
               "page_title": "테스트"}]
    저장폴더 = dl.process_images(images, base_result_dir=결과폴더)

    assert 저장폴더 is None, "이미 받은 이미지는 건너뛰어야 한다"


# ──────────────────────────────────────────────────────────────
# 7. 새로 추가한 설정 키의 하위호환
# ──────────────────────────────────────────────────────────────
@pytest.mark.parametrize("새_키, 기대_기본값", [
    ("use_scope", False),
    ("scope_selector", ""),
    ("crawl_depth", 1),
])
def test_새로_저장하기_시작한_수집범위_설정도_옛_저장본에서_안전하다(tmp_path, 새_키, 기대_기본값):
    """수집 범위·깊이는 이번에 처음 저장 대상이 됐다. 옛 파일에는 이 키가 없다."""
    path = tmp_path / "config" / "settings.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"min_width": 250, "headless": False}), encoding="utf-8")

    cfg = ConfigManager(config_path=str(path))

    assert cfg.get(새_키) == 기대_기본값
    assert cfg.get("min_width") == 250, "기존 선택은 그대로 보존되어야 한다"


# ──────────────────────────────────────────────────────────────
# 8. UI 일관성 — 종속 입력칸은 숨기지 않고 비활성으로만 처리한다
# ──────────────────────────────────────────────────────────────
def test_종속_입력칸을_숨기지_않는다():
    """
    ⛔ 회귀 방지: 예전에는 '특정 영역만 수집' 체크 시 pack() 으로 입력칸을 뒤늦게 추가해서
       pack 순서상 맨 끝에 붙었다. 자기 체크박스 옆이 아니라 '크롤링 깊이' 버튼 오른쪽에
       나타나면서 줄 전체가 밀렸다. 지금은 항상 같은 자리에 두고 비활성으로만 표시한다.
    """
    from src.ui import main_window

    소스 = _코드만(main_window)
    assert "pack_forget" not in 소스, "레이아웃을 흔드는 숨김/표시 방식이 되살아났다"
    assert "_apply_dependency_states" in 소스


def test_종속_입력칸_세_개가_같은_규칙으로_관리된다():
    """세 입력칸(영역·로그인대기·페이지선택자)이 한 함수에서 함께 처리되어야 일관성이 유지된다."""
    from src.ui import main_window

    함수 = _코드만(main_window.MainWindow._apply_dependency_states)
    for 위젯 in ("scope_entry", "login_wait_entry", "paging_entry"):
        assert 위젯 in 함수, f"{위젯} 이 공통 규칙에서 빠졌다"


def test_세_탭이_모두_같은_줄_수를_가진다():
    """
    ⛔ 회귀 방지: 예전에는 '계정 및 접속' 탭만 2줄이어서 아래가 텅 비었고,
       탭을 누를 때마다 밀도가 확 달라져 다른 화면처럼 보였다.
    """
    from src.ui import main_window

    소스 = _코드만(main_window.MainWindow.create_widgets)
    호출 = re.findall(r"_form_row\(\s*(tab_\w+)\s*,\s*(\d+)", 소스)

    탭별_줄 = {}
    for 탭, 줄 in 호출:
        탭별_줄.setdefault(탭, []).append(int(줄))

    assert len(탭별_줄) == 3, f"설정 탭이 3개여야 한다: {list(탭별_줄)}"
    for 탭, 줄들 in 탭별_줄.items():
        assert sorted(줄들) == list(range(main_window.FORM_ROWS_PER_TAB)), \
            f"{탭} 의 줄 번호가 0~{main_window.FORM_ROWS_PER_TAB - 1} 이 아니다: {sorted(줄들)}"


def test_설정_탭의_모든_줄은_공용_폼_함수로_만든다():
    """⛔ 회귀 방지: 탭마다 제각각 pack() 으로 배치하면 라벨 열이 어긋난다."""
    from src.ui import main_window

    소스 = _코드만(main_window.MainWindow.create_widgets)
    # 설정 탭에 위젯을 직접 pack/grid 하는 코드가 있으면 폼 규칙을 우회한 것이다
    for 탭 in ("tab_basic", "tab_filter", "tab_auth"):
        assert f"{탭}," in 소스 or f"{탭})" in 소스
        assert f"ctk.CTkFrame({탭}" not in 소스, f"{탭} 에 별도 프레임을 직접 만들고 있다"


@pytest.mark.parametrize("규격", [
    "FORM_LABEL_WIDTH", "FORM_ROW_PAD_Y", "FIELD_GAP",
    "FIELD_W_TINY", "FIELD_W_MEDIUM", "FIELD_W_WIDE",
])
def test_입력칸_폭과_여백은_상수로_관리된다(규격):
    """⛔ 회귀 방지: 예전에는 폭이 60/200/250/320/350, 여백이 2/5/(8,5)/(15,5)/(20,5) 로 제각각이었다."""
    from src.ui import main_window

    assert hasattr(main_window, 규격), f"{규격} 상수가 없다"
    # 선언만 하고 안 쓰면 의미가 없다 — 선언 줄을 뺀 나머지 코드에서 실제 사용 여부를 본다
    소스 = _코드만(main_window)
    사용 = [줄 for 줄 in 소스.splitlines()
            if 규격 in 줄 and not 줄.strip().startswith(f"{규격} =")]
    assert 사용, f"{규격} 을 선언만 하고 실제로 쓰지 않는다(매직넘버가 남아 있다는 뜻)"


def test_비활성_입력칸은_눈에_보이게_흐려진다():
    """
    ⛔ 회귀 방지: state="disabled" 만 걸면 CTkEntry 는 활성 상태와 '픽셀 단위로 동일'하다
       (실제 캡처를 비교해 확인함). 그러면 사용자는 입력해도 무시되는 칸인 줄 모른다.
    """
    from src.ui import main_window

    함수 = _코드만(main_window.MainWindow._apply_dependency_states)
    assert "text_color" in 함수, "글자색을 함께 흐리게 하지 않으면 비활성이 보이지 않는다"
    assert "border_color" in 함수, "테두리색도 함께 흐리게 해야 한다"
    assert "state=\"normal\"" in 함수 and "state=\"disabled\"" in 함수


def test_안내문구는_직접_구현한다():
    """
    ⛔ 회귀 방지: customtkinter 의 placeholder_text 는 textvariable 을 지정하면
       내부 조건(`self._textvariable == ""` — StringVar 객체와 문자열 비교)이 항상 False 라서
       절대 표시되지 않는다. 이 창의 모든 입력칸은 textvariable 을 쓰므로 직접 구현해야 한다.
    """
    from src.ui import main_window

    소스 = _코드만(main_window)
    assert "placeholder_text" not in 소스, \
        "표시되지 않는 placeholder_text 를 다시 쓰고 있다 (_attach_hint 를 쓸 것)"
    assert "_attach_hint" in 소스


def test_삭제된_버튼을_안내하는_문구가_남아있지_않다():
    """⛔ 회귀 방지: 없어진 '이어받기 기록 초기화' 버튼을 안내하면 사용자가 찾지 못한다.
    (⛔ 주석에 '제거했다'고 기록해 둔 것은 정상이므로 주석은 검사에서 제외한다)"""
    from src.ui import main_window

    assert "이어받기 기록 초기화" not in _코드만(main_window), \
        "제거한 버튼 이름이 사용자에게 보이는 문구에 남아 있다"
    assert "reset_download_history" not in _코드만(main_window), \
        "버튼 처리 함수가 남아 있다"
