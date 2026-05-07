import logging
import sys
import os

def setup_logger():
    if not os.path.exists("logs"):
        os.makedirs("logs")
        
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler("logs/bot.log")
        ]
    )
    return logging.getLogger(__name__)

logger = setup_logger()
