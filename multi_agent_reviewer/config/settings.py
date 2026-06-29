"""配置管理 - Qwen (LLM) + Milvus (向量数据库)"""
from pydantic_settings import BaseSettings
from typing import Optional
import os


class Settings(BaseSettings):
    """应用配置"""
    # === Qwen LLM 配置 (兼容 OpenAI SDK) ===
    qwen_api_key: str = os.getenv("QWEN_API_KEY", "")
    qwen_model: str = os.getenv("QWEN_MODEL", "qwen-plus")
    qwen_base_url: str = os.getenv(
        "QWEN_BASE_URL",
        "https://dashscope.aliyuncs.com/compatible-mode/v1"
    )

    # Agent 模型分配 (可单独指定)
    analyzer_model: str = "qwen-plus"
    security_model: str = "qwen-plus"
    linter_model: str = "qwen-plus"
    reviewer_model: str = "qwen-plus"

    # === Milvus 向量数据库配置 ===
    milvus_host: str = os.getenv("MILVUS_HOST", "localhost")
    milvus_port: int = int(os.getenv("MILVUS_PORT", "19530"))
    milvus_collection: str = os.getenv("MILVUS_COLLECTION", "code_review_memory")
    milvus_dimension: int = 1024

    # 超时配置（秒）
    agent_timeout: int = 60
    total_timeout: int = 300

    # 重试配置
    max_retries: int = 3
    retry_delay: int = 5

    # 质量阈值
    min_quality_score: float = 0.7

    # Redis 配置
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0

    # 记忆窗口大小
    memory_window_size: int = 10

    # 可观测性
    enable_tracing: bool = True
    trace_output_path: str = "./data/traces"

    # API配置
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    class Config:
        env_file = ".env"
        extra = "allow"


settings = Settings()
