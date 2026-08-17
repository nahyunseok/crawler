"""[local-json-store] 로컬 JSON 저장의 원자성·복구 점검.

이 프로그램은 3종의 JSON 을 로컬에 쓴다 — settings.json / license_cache.json /
results/.history/<도메인>.json. 파일이 깨지면 사용자의 설정·인증·수집기록이 통째로
날아가므로, '쓰다가 죽어도 원본은 온전한가'와 '깨진 파일을 만나도 살아나는가'를 검사한다.
"""
import json
import os

import pytest

from src.core.image_downloader import ImageDownloader
from src.utils.config_manager import ConfigManager


@pytest.fixture
def cfg(tmp_path):
    """임시 폴더에 격리된 ConfigManager (사용자의 실제 settings.json 을 건드리지 않는다)."""
    return ConfigManager(config_path=str(tmp_path / "config" / "settings.json"))


# ──────────────────────────────────────────────────────────
# 원자성 — 쓰다가 죽어도 반쪽 파일이 남지 않아야 한다
# ──────────────────────────────────────────────────────────
def test_저장은_임시파일_교체_방식이라_잔재가_남지_않는다(cfg):
    cfg.set_many({"min_width": 321, "min_height": 123})

    assert not os.path.exists(f"{cfg.config_path}.tmp"), ".tmp 잔재가 남으면 원자적 교체가 안 된 것"
    with open(cfg.config_path, encoding="utf-8") as f:
        saved = json.load(f)          # 파싱 성공 = 완성된 파일만 노출됐다는 뜻
    assert saved["min_width"] == 321
    assert saved["min_height"] == 123


def test_set_many_는_설정_18개를_바꿔도_파일을_한_번만_쓴다(cfg, monkeypatch):
    """⛔ 회귀 방지: 예전에는 set() 18번 = 파일 쓰기 18번이었다.
    슬라이더를 움직일 때마다 이게 반복되어 손상 위험이 18배였다."""
    write_count = {"n": 0}
    original = ConfigManager.save_config

    def counting_save(self, config):
        write_count["n"] += 1
        return original(self, config)

    monkeypatch.setattr(ConfigManager, "save_config", counting_save)

    cfg.set_many({f"probe_{i}": i for i in range(18)})
    assert write_count["n"] == 1, f"18개 저장에 파일 쓰기 {write_count['n']}회 — 1회여야 한다"


def test_빈_dict_를_넘기면_불필요한_쓰기를_하지_않는다(cfg, monkeypatch):
    write_count = {"n": 0}
    monkeypatch.setattr(ConfigManager, "save_config",
                        lambda self, config: write_count.__setitem__("n", write_count["n"] + 1))
    cfg.set_many({})
    assert write_count["n"] == 0


# ──────────────────────────────────────────────────────────
# 복구 — 깨진 파일을 만나도 프로그램은 살아야 한다
# ──────────────────────────────────────────────────────────
@pytest.mark.parametrize("깨진_내용", [
    '{"min_width": 200,',        # 쓰다가 죽어 잘린 JSON
    '',                          # 빈 파일
    'not json at all',           # 완전 쓰레기
    '[1, 2, 3]',                 # JSON 이지만 객체가 아님
])
def test_설정파일이_깨져도_기본값으로_살아난다(tmp_path, 깨진_내용):
    path = tmp_path / "config" / "settings.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(깨진_내용, encoding="utf-8")

    cfg = ConfigManager(config_path=str(path))          # 예외 없이 살아나야 한다
    assert cfg.get("min_width") == 100, "깨진 파일이면 기본값으로 복구되어야 한다"
    assert cfg.get("respect_robots") is True, "안전 기본값(robots 준수)이 꺼져선 안 된다"


def test_저장_실패는_반드시_드러난다(cfg, monkeypatch):
    """⛔ 침묵 실패 금지: 저장이 실패했는데 성공처럼 보이면, 사용자는 설정이
    저장된 줄 알고 계속 쓰다가 재실행 시 값이 되돌아간 것을 발견한다."""
    def 쓰기_불가(*args, **kwargs):
        raise PermissionError("access is denied")

    monkeypatch.setattr("builtins.open", 쓰기_불가)

    결과 = cfg.set_many({"min_width": 999})

    assert 결과 is False, "실패했는데 True 를 돌려주면 UI가 성공으로 오인한다"
    assert cfg.last_error, "실패 사유가 남아야 UI가 사용자에게 알려줄 수 있다"


def test_저장_성공시에는_True_를_돌려준다(cfg):
    assert cfg.set_many({"min_width": 456}) is True
    assert cfg.last_error is None


def test_저장이_실패해도_이번_실행에는_설정이_적용된다(cfg, monkeypatch):
    """디스크에 못 써도 프로그램은 계속 동작해야 한다 — 실패를 알리되 기능은 유지."""
    def 쓰기_불가(*args, **kwargs):
        raise PermissionError("access is denied")

    monkeypatch.setattr("builtins.open", 쓰기_불가)
    assert cfg.set_many({"min_width": 777}) is False

    monkeypatch.undo()
    assert cfg.get("min_width") == 777, "저장 실패 시 메모리 반영까지 잃으면 수집 설정이 무시된다"


def test_쓰기_권한이_없으면_사용자_데이터_폴더로_대체된다(monkeypatch, tmp_path):
    """Program Files 처럼 권한 없는 곳에 설치된 경우를 흉내낸다."""
    from src.utils import config_manager as cm

    monkeypatch.setattr(cm, "_is_writable_dir", lambda d: False)
    monkeypatch.setattr(cm.os, "getcwd", lambda: str(tmp_path / "readonly"))

    resolved = cm.resolve_config_path()
    assert str(tmp_path / "readonly") not in resolved, "권한 없는 폴더를 그대로 쓰면 저장이 조용히 실패한다"
    assert resolved.endswith(os.path.join("config", "settings.json"))


# ──────────────────────────────────────────────────────────
# 이어받기 기록 — 사이트별 격리
# ──────────────────────────────────────────────────────────
def test_이어받기_기록은_사이트별로_분리된다(tmp_path):
    """⛔ 회귀 방지: 예전에는 download_history.json 하나에 전 사이트를 몰아 넣어서
    A사이트를 받고 나면 B사이트 재수집이 아예 안 됐다."""
    a = ImageDownloader.get_history_path(str(tmp_path), "https://a-site.co.kr/page")
    b = ImageDownloader.get_history_path(str(tmp_path), "https://b-site.com/page")

    assert a != b, "사이트가 다르면 기록 파일도 달라야 한다"
    assert "a-site.co.kr" in os.path.basename(a)
    assert "b-site.com" in os.path.basename(b)


@pytest.mark.parametrize("악성_url", [
    "https://../../etc/passwd/page",
    "https://a/..\\..\\windows\\system32",
    "https://a<>:|?*b.com/x",
])
def test_기록_파일명에_경로조작_문자가_섞이지_않는다(tmp_path, 악성_url):
    """호스트명이 그대로 파일명이 되므로 Path Traversal 방어가 필수다."""
    path = ImageDownloader.get_history_path(str(tmp_path), 악성_url)
    name = os.path.basename(path)

    assert ".." not in name
    assert not set(name) & set('<>:"|?*\\/'), f"위험 문자가 남았다: {name}"
    # 반드시 지정한 .history 폴더 '안'에 머물러야 한다
    assert os.path.realpath(path).startswith(os.path.realpath(str(tmp_path)))


def test_기록_초기화는_구버전_전역파일까지_함께_지운다(tmp_path):
    base = str(tmp_path)
    ImageDownloader.get_history_path(base, "https://a.com/x")     # .history 폴더 생성
    (tmp_path / ".history" / "a.com.json").write_text("[]", encoding="utf-8")
    (tmp_path / "download_history.json").write_text("[]", encoding="utf-8")   # 구버전 전역 기록

    removed = ImageDownloader.clear_history(base)

    assert removed == 2, "사이트별 기록과 구버전 전역 기록 모두 지워져야 한다"
    assert not (tmp_path / "download_history.json").exists()
