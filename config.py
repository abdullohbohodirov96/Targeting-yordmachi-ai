import os
from dotenv import load_dotenv

# load .env file
load_dotenv()

TOKEN = os.getenv("TOKEN")
GROUP_ID = os.getenv("GROUP_ID")
META_ACCESS_TOKEN = os.getenv("META_ACCESS_TOKEN")
META_AD_ACCOUNT_ID = os.getenv("META_AD_ACCOUNT_ID")
