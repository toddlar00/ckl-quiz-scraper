"""Configuration loaded from environment variables / .env file."""

import os
from dotenv import load_dotenv

load_dotenv()

# CKL Credentials
USERNAME = os.getenv("CKL_USERNAME", "")
PASSWORD = os.getenv("CKL_PASSWORD", "")
BASE_URL = os.getenv("CKL_BASE_URL", "https://coreknowledgeforlawyers.com")

# West Academic Credentials
WA_USERNAME = os.getenv("WA_USERNAME", "")
WA_PASSWORD = os.getenv("WA_PASSWORD", "")
WA_BASE_URL = os.getenv("WA_BASE_URL", "https://subscription.westacademic.com")
WA_LOGIN_METHOD = os.getenv("WA_LOGIN_METHOD", "form")  # "form" or "google"

# Selenium settings
HEADLESS = os.getenv("CKL_HEADLESS", "true").lower() == "true"
PAGE_LOAD_TIMEOUT = int(os.getenv("CKL_PAGE_LOAD_TIMEOUT", "30"))
IMPLICIT_WAIT = int(os.getenv("CKL_IMPLICIT_WAIT", "10"))

# Proxy / VPN — route browser traffic through a proxy server
# Supports HTTP, HTTPS, and SOCKS5 proxies.
# Examples:
#   http://proxy.example.com:8080
#   socks5://127.0.0.1:1080
#   http://user:pass@proxy.example.com:8080
PROXY_URL = os.getenv("CKL_PROXY_URL", "")

# Rate limiting — delay in seconds between questions to avoid overloading the site
REQUEST_DELAY = float(os.getenv("CKL_REQUEST_DELAY", "1.0"))
