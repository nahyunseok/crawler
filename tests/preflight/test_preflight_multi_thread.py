"""[multi-thread] 스레드 공유 데이터 점검.

이 프로그램의 스레드 구조:
  ① UI 스레드 — 위젯 갱신
  ② 수집 스레드 1개 — CrawlerEngine
  ③ 다운로드 스레드 5개 — ThreadPoolExecutor(max_workers=5)
②③ 이 같은 ConfigManager 를 읽고, ③ 은 스레드별 requests 세션을 각자 만든다.
"""
import json
import threading

from src.core.image_downloader import ImageDownloader
from src.utils.config_manager import ConfigManager


def test_여러_스레드가_동시에_저장해도_설정파일이_깨지지_않는다(tmp_path):
    """원자적 교체(os.replace) 덕분에, 읽는 쪽은 항상 '완성된 파일'만 본다.
    파일이 한 번이라도 파싱 불가 상태로 노출되면 사용자 설정이 초기화된다."""
    cfg = ConfigManager(config_path=str(tmp_path / "config" / "settings.json"))
    깨진_읽기 = []
    멈춤 = threading.Event()

    def 계속_저장():
        for i in range(60):
            cfg.set_many({"min_width": i, "min_height": i * 2})
        멈춤.set()

    def 계속_읽기():
        while not 멈춤.is_set():
            try:
                with open(cfg.config_path, encoding="utf-8") as f:
                    json.load(f)
            except (FileNotFoundError, PermissionError):
                # 교체가 일어나는 찰나에는 '읽을 수 없음'이 정상이다.
                # (윈도우는 os.replace 순간 대상 파일 접근을 막아 PermissionError 를 던진다)
                # 중요한 건 '읽혔다면 반드시 온전해야 한다'는 것.
                pass
            except json.JSONDecodeError as e:
                깨진_읽기.append(str(e))   # 반쪽 파일이 노출됐다 — 이건 실패

    writers = [threading.Thread(target=계속_저장) for _ in range(3)]
    reader = threading.Thread(target=계속_읽기, daemon=True)
    reader.start()
    for w in writers:
        w.start()
    for w in writers:
        w.join()
    멈춤.set()
    reader.join(timeout=5)

    assert not 깨진_읽기, f"반쪽짜리 JSON 이 노출됐다: {깨진_읽기[:3]}"
    with open(cfg.config_path, encoding="utf-8") as f:
        json.load(f)                      # 최종 상태도 온전해야 한다


def test_동시_저장_후에도_설정_키가_유실되지_않는다(tmp_path):
    """set_many 는 '현재 상태 + 변경분' 을 합쳐 쓴다. 동시에 써도 기본 키가 사라지면 안 된다."""
    cfg = ConfigManager(config_path=str(tmp_path / "config" / "settings.json"))

    def 저장(키):
        for i in range(30):
            cfg.set_many({키: i})

    threads = [threading.Thread(target=저장, args=(f"probe_{n}",)) for n in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    with open(cfg.config_path, encoding="utf-8") as f:
        saved = json.load(f)
    for 필수키 in ("respect_robots", "use_resume", "min_width", "max_image_mb"):
        assert 필수키 in saved, f"동시 저장 중 기본 키 '{필수키}' 가 유실됐다"


def test_다운로드_스레드는_각자_세션을_쓴다(tmp_path):
    """requests.Session 은 스레드 안전이 보장되지 않아 공유하면 간헐적 실패가 난다.

    ⛔ 테스트 작성 주의: 세션 '객체'를 담아 참조를 살려 둔 상태로 비교해야 한다.
       id() 만 담으면, 먼저 끝난 스레드의 세션이 GC 된 뒤 그 주소가 재사용되어
       '서로 다른 세션'이 같은 id 로 보이는 가짜 실패가 난다(실제로 5개→3개로 겪음).
       배리어로 5개 스레드가 동시에 세션을 들고 있는 상태를 만든다.
    """
    downloader = ImageDownloader(ConfigManager(config_path=str(tmp_path / "config" / "settings.json")))
    downloader._set_cookies([{"name": "SESSIONID", "value": "abc123"}])

    스레드수 = 5
    배리어 = threading.Barrier(스레드수)
    세션들 = []
    lock = threading.Lock()

    def 세션_확보():
        s = downloader._get_session()
        with lock:
            세션들.append(s)          # 객체 자체를 보관 → GC 로 인한 id 재사용 방지
        배리어.wait(timeout=5)        # 모두가 세션을 들고 있는 순간까지 대기

    threads = [threading.Thread(target=세션_확보) for _ in range(스레드수)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert len(세션들) == 스레드수
    assert len({id(s) for s in 세션들}) == 스레드수, "스레드끼리 같은 세션을 공유하고 있다"


def test_로그인_쿠키가_모든_스레드_세션에_실린다(tmp_path):
    """⛔ 회귀 방지: 쿠키를 안 넘기면 수동 로그인해도 회원 전용 이미지가 전부 403 이 된다."""
    downloader = ImageDownloader(ConfigManager(config_path=str(tmp_path / "config" / "settings.json")))
    downloader._set_cookies([
        {"name": "SESSIONID", "value": "abc123"},
        {"name": "AUTH", "value": "xyz"},
        {"name": "BROKEN", "value": None},      # 값 없는 쿠키는 조용히 무시되어야 한다
    ])

    결과 = []

    def 확인():
        결과.append(dict(downloader._get_session().cookies))

    threads = [threading.Thread(target=확인) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    for cookies in 결과:
        assert cookies.get("SESSIONID") == "abc123"
        assert cookies.get("AUTH") == "xyz"
        assert "BROKEN" not in cookies


def test_중지_신호는_다운로드_직전에_즉시_반영된다(tmp_path):
    """중지를 눌렀는데도 네트워크 요청이 계속 나가면 '멈추지 않는 프로그램'이 된다."""
    downloader = ImageDownloader(ConfigManager(config_path=str(tmp_path / "config" / "settings.json")))
    stop = threading.Event()
    stop.set()

    호출됨 = {"n": 0}
    downloader._get_session = lambda: (_ for _ in ()).throw(AssertionError("중지 후 요청이 나갔다"))

    결과 = downloader._fetch_bytes("https://example.invalid/a.jpg", "https://example.invalid", stop)
    assert 결과 is None
    assert 호출됨["n"] == 0
