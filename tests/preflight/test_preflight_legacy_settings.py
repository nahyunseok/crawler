"""[legacy-settings] 기존 고객의 '옛 저장본' 하위호환 점검.

이미 판매된 버전을 쓰던 고객 PC에는 ①새 옵션이 없는 옛 settings.json 과
②서명이 없는 옛 라이선스 캐시가 남아 있다. 업데이트 후 이것들이 어떻게 처리되는지가
그대로 '고객 문의'로 이어지므로 전수 검사한다.
"""
import json

import pytest

from src.core.license_client import OnlineLicenseClient
from src.utils.config_manager import ConfigManager

# v1.0.15 시절의 settings.json (새 옵션들이 아예 없다)
구버전_설정 = {
    "min_width": 250,
    "ext_jpg": True,
    "ext_png": False,
    "headless": False,
    "exclude_keywords": "logo, icon",
}


def _옛_설정_파일(tmp_path, 내용):
    path = tmp_path / "config" / "settings.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(내용, ensure_ascii=False), encoding="utf-8")
    return path


def test_옛_설정본의_사용자_선택은_그대로_보존된다(tmp_path):
    cfg = ConfigManager(config_path=str(_옛_설정_파일(tmp_path, 구버전_설정)))

    assert cfg.get("min_width") == 250, "사용자가 고른 값이 기본값으로 덮여선 안 된다"
    assert cfg.get("ext_png") is False, "False 로 끈 옵션이 되살아나선 안 된다"
    assert cfg.get("headless") is False
    assert cfg.get("exclude_keywords") == "logo, icon"


@pytest.mark.parametrize("새_옵션, 기대_기본값", [
    ("respect_robots", True),          # robots 준수는 반드시 '켜짐'으로 시작해야 한다(준법)
    ("use_resume", True),
    ("min_height", 100),
    ("ext_allow_base64", True),
    ("max_image_mb", 20),
    ("max_pagination_pages", 30),
])
def test_새_옵션은_옛_설정본에서도_안전한_기본값으로_병합된다(tmp_path, 새_옵션, 기대_기본값):
    """⛔ 회귀 방지: 병합하지 않고 파일 내용만 쓰면, 옛 파일에 키가 없어서
    신규 기능이 '조용히 꺼진 상태'로 동작한다(가장 찾기 어려운 버그)."""
    cfg = ConfigManager(config_path=str(_옛_설정_파일(tmp_path, 구버전_설정)))
    assert cfg.get(새_옵션) == 기대_기본값


def test_병합_결과가_파일에도_반영되어_다음_실행부터는_보인다(tmp_path):
    path = _옛_설정_파일(tmp_path, 구버전_설정)
    ConfigManager(config_path=str(path))

    saved = json.loads(path.read_text(encoding="utf-8"))
    assert "respect_robots" in saved, "새 키가 파일에 기록되어야 사용자가 직접 확인·수정할 수 있다"
    assert saved["min_width"] == 250, "마이그레이션이 기존 값을 훼손해선 안 된다"


def test_없어진_옛_키가_있어도_새_키_병합을_놓치지_않는다(tmp_path):
    """⛔ 회귀 방지: 예전에는 '키 개수'만 비교해서, 사라진 옛 키와 새 키의
    개수가 우연히 같으면 마이그레이션을 건너뛰었다."""
    섞인_설정 = dict(구버전_설정)
    섞인_설정["삭제된_옛_옵션_1"] = "x"
    섞인_설정["삭제된_옛_옵션_2"] = "y"

    path = _옛_설정_파일(tmp_path, 섞인_설정)
    cfg = ConfigManager(config_path=str(path))

    assert cfg.get("respect_robots") is True
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert "respect_robots" in saved


# ──────────────────────────────────────────────────────────
# 라이선스 캐시 하위호환 (보안과 직결)
# ──────────────────────────────────────────────────────────
@pytest.mark.parametrize("옛_캐시_형태, 설명", [
    ('{"key":"OLD","valid_until":99999999999,"data":{"expiration":"2099-01-01"}}', "평문 JSON"),
    ('eyJrZXkiOiAiT0xEIn0=', "서명 없는 Base64"),
    ('', "빈 파일"),
    ('!!!broken!!!', "손상된 내용"),
])
def test_서명없는_옛_라이선스_캐시는_무효_처리된다(tmp_path, monkeypatch, 옛_캐시_형태, 설명):
    """⛔ 이게 통과되면 만료일을 손으로 고친 캐시로 영구 무료 사용이 가능해진다.
    옛 고객은 키를 한 번 재입력해야 하지만, 그것이 의도된 동작이다(CHANGELOG 고지)."""
    client = OnlineLicenseClient("https://example.invalid/exec")
    cache = tmp_path / "license_cache.json"
    cache.write_text(옛_캐시_형태, encoding="utf-8")
    monkeypatch.setattr(client, "cache_file", str(cache))

    assert client.check_local_validity() is None, f"{설명} 캐시가 통과되면 안 된다"
    assert client.get_cached_key() == ""


def test_새로_저장한_캐시는_같은_PC에서_정상_인식된다(tmp_path, monkeypatch):
    """서명 검증이 너무 엄격해서 '정상 사용자'까지 막으면 안 된다(과잉 차단 방지)."""
    client = OnlineLicenseClient("https://example.invalid/exec")
    monkeypatch.setattr(client, "cache_file", str(tmp_path / "license_cache.json"))

    client._save_cache("REAL-KEY-1234", {"valid": True, "data": {"expiration": "2099-12-31"}})

    cached = client.check_local_validity()
    assert cached and cached["valid"] is True
    assert client.get_cached_key() == "REAL-KEY-1234"


def test_캐시_내용을_손으로_고치면_즉시_무효가_된다(tmp_path, monkeypatch):
    client = OnlineLicenseClient("https://example.invalid/exec")
    cache = tmp_path / "license_cache.json"
    monkeypatch.setattr(client, "cache_file", str(cache))
    client._save_cache("REAL-KEY-1234", {"valid": True, "data": {"expiration": "2026-01-01"}})

    # 만료일을 2099년으로 위조 (서명은 그대로 둔다 → 서명 불일치로 걸려야 한다)
    import base64
    envelope = json.loads(base64.b64decode(cache.read_text(encoding="utf-8")).decode("utf-8"))
    envelope["payload"] = envelope["payload"].replace("2026-01-01", "2099-01-01")
    cache.write_text(base64.b64encode(json.dumps(envelope).encode()).decode(), encoding="utf-8")

    assert client.check_local_validity() is None, "위조된 캐시가 통과되면 라이선스가 무력화된다"


def test_다른_PC에서_복사한_캐시는_거부된다(tmp_path, monkeypatch):
    client = OnlineLicenseClient("https://example.invalid/exec")
    monkeypatch.setattr(client, "cache_file", str(tmp_path / "license_cache.json"))
    client._save_cache("REAL-KEY-1234", {"valid": True, "data": {"expiration": "2099-12-31"}})

    # HWID 가 다른 PC 인 척한다 → 서명 키가 달라지므로 검증에 실패해야 한다
    monkeypatch.setattr(client, "hwid", "OTHERPC00000000")
    assert client.check_local_validity() is None
