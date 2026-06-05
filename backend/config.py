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

    # 预计算回放配置（A组 / plugin_structured）
    PLAYBACK_TOTAL_DURATION: float = float(os.getenv("PLAYBACK_TOTAL_DURATION", "30.0"))
    PLAYBACK_CHUNK_SIZE: int = int(os.getenv("PLAYBACK_CHUNK_SIZE", "150"))
    PLAYBACK_THINKING_CHUNK_SIZE: int = int(os.getenv("PLAYBACK_THINKING_CHUNK_SIZE", "100"))
    PRECOMPUTE_CACHE_DIR: str = os.getenv(
        "PRECOMPUTE_CACHE_DIR",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache")
    )


config = Config()
