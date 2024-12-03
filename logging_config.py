import logging
from config import LOG_FILE_NAME, LOG_LEVEL
import sys
def get_logger(log_name):
    logger = logging.getLogger(log_name)
    if not logger.hasHandlers():
        logger.setLevel(LOG_LEVEL)
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

        file_handler = logging.FileHandler(f"{LOG_FILE_NAME}")
        console_handler = logging.StreamHandler(sys.stdout)
        file_handler.setFormatter(formatter)
        console_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
        logger.addHandler(console_handler)
    return logger