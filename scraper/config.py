import os
from dotenv import load_dotenv

load_dotenv()

USERNAME = os.getenv("CKL_USERNAME", "")
PASSWORD = os.getenv("CKL_PASSWORD", "")
BASE_URL = os.getenv("CKL_BASE_URL", "https://coreknowledgeforlawyers.com")

# Selenium settings
HEADLESS = os.getenv("CKL_HEADLESS", "true").lower() == "true"
PAGE_LOAD_TIMEOUT = int(os.getenv("CKL_PAGE_LOAD_TIMEOUT", "30"))
IMPLICIT_WAIT = int(os.getenv("CKL_IMPLICIT_WAIT", "10"))
