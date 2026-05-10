"""
Application configuration and logging setup.
"""
import os
import logging

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class Config:
    # DeepSeek LLM配置
    LLM_API_KEY = os.getenv("LLM_API_KEY", "")
    LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.deepseek.com")
    LLM_MODEL = os.getenv("LLM_MODEL", "deepseek-v4-pro")

    # Bocha搜索配置
    BOCHA_API_KEY = os.getenv("BOCHA_API_KEY", "")
    BOCHA_BASE_URL = os.getenv("BOCHA_BASE_URL", "https://api.bocha.cn/v1/web-search")

    # Tavily搜索配置
    TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")

    # 服务配置
    HOST = os.getenv("HOST", "0.0.0.0")
    PORT = int(os.getenv("PORT", "8000"))
    MAX_CONCURRENT_CHECKS = int(os.getenv("MAX_CONCURRENT_CHECKS", "2"))


config = Config()
