"""pytest 공통 설정 — 프로젝트 루트를 import 경로에 넣는다.

⛔ 이게 없으면 `from src.utils...` 임포트가 실패한다(테스트는 tests/ 안에서 실행되므로).
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
