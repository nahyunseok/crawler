import logging
import os
from datetime import datetime
from logging.handlers import RotatingFileHandler
import sys

# 로그 파일 1개당 최대 크기와 보관 개수 (무한정 커지는 것 방지)
MAX_LOG_BYTES = 5 * 1024 * 1024   # 5MB
BACKUP_COUNT = 3


def _resolve_log_dir():
    """
    로그 폴더 경로를 정한다.
    1순위: 실행 폴더의 logs/  (사용자가 찾기 쉬움)
    2순위: 사용자 데이터 폴더 (Program Files 처럼 쓰기 권한이 없는 곳에 설치된 경우)
    ⛔ 이 폴백이 없으면 권한 없는 폴더에 설치했을 때 프로그램이 시작조차 못 한다.
    """
    candidate = os.path.join(os.getcwd(), "logs")
    try:
        os.makedirs(candidate, exist_ok=True)
        # 실제로 쓸 수 있는지 확인
        probe = os.path.join(candidate, ".write_test")
        with open(probe, "w", encoding="utf-8") as f:
            f.write("ok")
        os.remove(probe)
        return candidate
    except Exception:
        try:
            from appdirs import user_data_dir
            fallback = os.path.join(user_data_dir("GeminiImageCrawler", "User"), "logs")
            os.makedirs(fallback, exist_ok=True)
            return fallback
        except Exception:
            return None


def setup_logger():
    """Sets up the application logger."""
    logger = logging.getLogger("CrawlerApp")
    logger.setLevel(logging.DEBUG)

    if logger.handlers:
        return logger

    # Stream Handler (Console)
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setLevel(logging.INFO)
    stream_formatter = logging.Formatter('%(levelname)s: %(message)s')
    stream_handler.setFormatter(stream_formatter)
    logger.addHandler(stream_handler)

    # File Handler (용량 제한 + 자동 순환)
    log_dir = _resolve_log_dir()
    if log_dir:
        log_filename = datetime.now().strftime("crawler_%Y-%m-%d.log")
        log_filepath = os.path.join(log_dir, log_filename)
        try:
            file_handler = RotatingFileHandler(
                log_filepath, maxBytes=MAX_LOG_BYTES, backupCount=BACKUP_COUNT, encoding="utf-8"
            )
            file_handler.setLevel(logging.DEBUG)
            file_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            file_handler.setFormatter(file_formatter)
            logger.addHandler(file_handler)
        except Exception:
            # 파일 로깅이 안 되더라도 프로그램은 정상 동작해야 한다
            pass

    return logger


def get_logger():
    """Returns the logger instance."""
    return logging.getLogger("CrawlerApp")
