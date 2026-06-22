"""配置管理"""
from pydantic_settings import BaseSettings
from typing import Optional
import os


class Settings(BaseSettings):
    """应用配置"""
    # LLM配置
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-4")
    openai_base_url: Optional[str] = os.getenv("OPENAI_BASE_URL", None)
    
    # Agent配置
    analyzer_model: str = "gpt-4"
    security_model: str = "gpt-4"
    linter_model: str = "gpt-4"
    reviewer_model: str = "gpt-4"
    
    # 超时配置（秒）
    agent_timeout: int = 60
    total_timeout: int = 300
    
    # 重试配置
    max_retries: int = 3
    retry_delay: int = 5
    
    # 质量阈值
    min_quality_score: float = 0.7
    
    # Redis配置
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0
    
    # 向量存储配置
    vector_store_type: str = "chroma"
    vector_store_path: str = "./data/vector_store"
    
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
