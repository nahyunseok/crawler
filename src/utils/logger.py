import logging
import os
from datetime import datetime
import sys

def setup_logger():
    """Sets up the application logger."""
    log_dir = os.path.join(os.getcwd(), "logs")
    os.makedirs(log_dir, exist_ok=True)
    
    log_filename = datetime.now().strftime("crawler_%Y-%m-%d.log")
    log_filepath = os.path.join(log_dir, log_filename)
    
    logger = logging.getLogger("CrawlerApp")
    logger.setLevel(logging.DEBUG)
    
    # File Handler
    file_handler = logging.FileHandler(log_filepath, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    file_handler.setFormatter(file_formatter)
    
    # Stream Handler (Console)
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setLevel(logging.INFO)
    stream_formatter = logging.Formatter('%(levelname)s: %(message)s')
    stream_handler.setFormatter(stream_formatter)
    
    # Add handlers
    if not logger.handlers:
        logger.addHandler(file_handler)
        logger.addHandler(stream_handler)
    
    return logger

def get_logger():
    """Returns the logger instance."""
    return logging.getLogger("CrawlerApp")
