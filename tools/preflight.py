#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""빌드 전 필수 품질점검 게이트(Preflight Quality Gate).

프로젝트 루트의 quality-checks.json 에 선언된 '프로그램 성질(traits)'을 읽어,
그 성질에 맞는 자동 점검(pytest 스위트·런타임 검사)을 실행하고
자동화할 수 없는 항목은 '수동 점검 질문'으로 출력한다.

    python tools/preflight.py            # 점검 실행(수동 질문 미검토 상태면 실패)
    python tools/preflight.py --ack      # 수동 질문 검토 완료를 선언하고 통과
    python tools/preflight.py --skip "긴급 사유"   # 게이트 건너뛰기(사유 필수·영구 로그)

설계 원칙(docs/빌드전_품질점검_기획.md):
  - 러너는 '보편 로직'만 담고, 프로젝트별 선언(성질·스위트 경로)은 JSON 에 둔다
    → 이 파일을 그대로 다른 프로젝트에 복사해도 동작한다(범용).
  - '침묵 실패 금지'를 게이트 자신에게도 적용: skip/ack 은 반드시 로그에 남긴다.
  - 실패 시 exit code 1 → build.py 가 이를 보고 버전 증가 '전'에 중단한다.

다른 AI/개발자 참고: 점검 항목의 배경은 docs/learning-notes.md
'출시 전 품질 점검 체크리스트 10가지' 참조.
"""
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_FILE = ROOT / "quality-checks.json"

# ── 성질(trait)별 '수동 점검 질문' — 자동화가 불가능한 설계 원칙들(보편 지식) ──
# 프로젝트가 quality-checks.json 의 traits 에 선언한 성질의 질문만 출력된다.
MANUAL_QUESTIONS = {
    "_common": [  # 모든 프로그램 공통
        "이번 변경에 '조용히 실패/축소'되는 경로가 없는가? (실패·축소는 반드시 로그/경고로 드러나야 함)",
    ],
    "gui": [
        "화면에 보이는 숫자·상태가 실제 로직과 '같은 공식(공유 함수)'을 쓰는가? (두 벌 복사 금지)",
    ],
    "scheduler": [
        "예약·재시도가 '절대시각' 기준인가? (상대시간이면 절전·재시작 때 어긋난다)",
    ],
    "platform-bot": [
        "이번 변경이 플랫폼 요청/발행을 더 빠르게 만들지 않는가? 빨라졌다면 경고·딜레이를 붙였는가? (계정 정지 직결)",
    ],
    "multi-thread": [
        "여러 스레드가 같은 데이터를 쓰는 지점에 락/스냅샷이 있는가?",
    ],
    "legacy-settings": [
        "새로 추가한 설정 키가 '옛 저장본'에서 기본값으로 안전하게 병합되는가?",
    ],
    "server": [
        "확인→저장 사이 끼어들기(경쟁 상태)가 DB 수준(원자적 연산/행 잠금)에서 막혀 있는가?",
        "여러 건 쓰기가 하나의 트랜잭션인가? (부분 저장 금지) 결제·주문류엔 멱등성 키가 있는가?",
    ],
}


def _load_config() -> dict:
    """quality-checks.json 을 읽는다. 없으면 안내 후 실패(게이트는 선언 없이는 통과 불가)."""
    if not CONFIG_FILE.exists():
        print("❌ quality-checks.json 이 없습니다 — 이 프로젝트의 성질(traits)을 먼저 선언하세요.")
        print('   예: {"traits": ["desktop-exe", "gui", "scheduler"], "regression": "tests"}')
        sys.exit(1)
    return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))


def _read_version() -> str:
    vf = ROOT / "version.txt"
    return vf.read_text(encoding="utf-8").strip() if vf.exists() else "?"


def _append_log(cfg: dict, kind: str, detail: str):
    """skip/ack 기록 — 몰래 건너뛰기 방지(게이트 자신에게도 침묵 실패 금지 적용)."""
    log_path = ROOT / cfg.get("skip_log", "troubleshooting/preflight-skips.log")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} | v{_read_version()} | {kind} | {detail}\n")


def _run_pytest(path: str) -> bool:
    """pytest 스위트 실행 — 통과 여부만 돌려준다(출력은 그대로 보여줌)."""
    r = subprocess.run([sys.executable, "-m", "pytest", str(ROOT / path), "-q"], cwd=ROOT)
    return r.returncode == 0


def _check_exe_not_running(exe_name: str) -> bool:
    """[desktop-exe] 운영 중인 exe 가 배포 폴더를 잠그면 빌드가 깨진다 — 실행 여부를 검사.
    (v1.0.51 릴리즈에서 실제로 겪은 실패: 운영 exe 가 dist/logs 를 잠가 PyInstaller 클린 실패)"""
    if sys.platform != "win32":
        return True
    # tasklist 출력은 시스템 코드페이지(한글 Windows=CP949)라 text=True(UTF-8)로 받으면 깨진다
    # → 바이트로 받아 관대하게 디코딩(찾는 exe 이름은 ASCII 라 손상 없음)
    raw = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {exe_name}.exe"],
                         capture_output=True).stdout or b""
    return f"{exe_name}.exe" not in raw.decode("utf-8", errors="ignore")


def main():
    ack = "--ack" in sys.argv
    cfg = _load_config()
    traits = list(cfg.get("traits", []))

    # ── 탈출구: --skip "사유" — 사유 없이는 못 건너뛰고, 건너뛴 기록은 영구히 남는다 ──
    if "--skip" in sys.argv:
        idx = sys.argv.index("--skip")
        reason = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else ""
        if not reason.strip():
            print("❌ --skip 은 사유가 필수입니다: python tools/preflight.py --skip \"긴급 핫픽스 사유\"")
            sys.exit(1)
        _append_log(cfg, "SKIP", reason)
        print(f"⚠️ 품질점검을 건너뜁니다(사유: {reason}) — 기록됨. 다음 릴리즈 전 반드시 점검하세요.")
        sys.exit(0)

    print(f"🛫 Preflight 품질점검 시작 — 성질: {', '.join(traits) or '(선언 없음)'}")
    results = []   # (항목, 통과 여부)

    # ── ① 공통: 회귀 테스트 전체(경계값·원자성·하위호환 스위트 포함) ──
    reg = cfg.get("regression", "tests")
    if (ROOT / reg).exists():
        ok = _run_pytest(reg)
        results.append((f"회귀 테스트({reg})", ok))
    else:
        results.append((f"회귀 테스트({reg}) — 경로 없음", False))

    # ── ② 성질별 자동 스위트(JSON 선언) — 회귀 경로 안에 있으면 ①에서 이미 실행됨 ──
    for trait, suites in (cfg.get("suites") or {}).items():
        if trait not in traits:
            continue
        for suite in suites:
            if suite.replace("\\", "/").startswith(reg.replace("\\", "/")):
                continue   # 중복 실행 방지
            results.append((f"[{trait}] {suite}", _run_pytest(suite)))

    # ── ③ 런타임 검사: 배포 자원 충돌(desktop-exe) ──
    if "desktop-exe" in traits and cfg.get("exe_name"):
        ok = _check_exe_not_running(cfg["exe_name"])
        results.append((f"[desktop-exe] 운영 exe({cfg['exe_name']}) 미실행 확인", ok))
        if not ok:
            print(f"   ↳ 실행 중인 {cfg['exe_name']}.exe 를 먼저 종료하세요(배포 폴더 잠금 → 빌드 실패).")

    # ── ④ 수동 점검 질문(자동화 불가 항목) — --ack 로 검토 완료를 명시해야 통과 ──
    questions = list(MANUAL_QUESTIONS["_common"])
    for t in traits:
        questions += MANUAL_QUESTIONS.get(t, [])
    if questions:
        print("\n📋 수동 점검 질문(자동화 불가 — 이번 변경 기준으로 검토):")
        for i, q in enumerate(questions, 1):
            print(f"   {i}. {q}")
        if ack:
            _append_log(cfg, "ACK", f"수동 {len(questions)}문항 검토 선언")
            results.append((f"수동 점검 {len(questions)}문항(--ack 검토 선언)", True))
        else:
            results.append((f"수동 점검 {len(questions)}문항 — 미검토(--ack 필요)", False))

    # ── 결과 요약 ──
    print("\n" + "─" * 50)
    all_ok = True
    for name, ok in results:
        print(f"  {'✅' if ok else '❌'} {name}")
        all_ok = all_ok and ok
    print("─" * 50)
    if all_ok:
        print("🛫 Preflight 통과 — 빌드를 진행해도 좋습니다.")
        sys.exit(0)
    print("⛔ Preflight 실패 — 위 ❌ 항목을 해결한 뒤 다시 실행하세요.")
    print("   (수동 질문만 남았다면 검토 후: python tools/preflight.py --ack)")
    sys.exit(1)


if __name__ == "__main__":
    main()
