"""Agent基类 - 含 Qwen LLM 客户端"""
from abc import ABC, abstractmethod
from typing import TypeVar, Generic, Optional
from datetime import datetime
import json

from openai import OpenAI

from core.state import SharedState, AgentType, AgentMessage
from config.settings import settings


T = TypeVar("T")


# ============================================================
# Qwen LLM 客户端 (兼容 OpenAI SDK)
# ============================================================

class QwenClient:
    """
    Qwen (通义千问) LLM 客户端

    使用 OpenAI 兼容 SDK 调用通义千问 API。
    """

    def __init__(self, model: str = None):
        self.api_key = settings.qwen_api_key
        self.base_url = settings.qwen_base_url
        self.model = model or settings.qwen_model
        self._client: OpenAI | None = None

    @property
    def client(self) -> OpenAI:
        if self._client is None:
            self._client = OpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
            )
        return self._client

    def chat(
        self,
        messages: list[dict],
        temperature: float = 0.3,
        max_tokens: int = 4096,
        response_format: dict = None,
    ) -> str:
        """
        调用 Qwen 聊天补全

        Args:
            messages: 消息列表 [{"role": "...", "content": "..."}]
            temperature: 采样温度 (0-1), 低值更确定
            max_tokens: 最大输出 Token 数
            response_format: 响应格式, e.g. {"type": "json_object"}

        Returns:
            模型回复文本
        """
        kwargs = dict(
            model=self.model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        if response_format:
            kwargs["response_format"] = response_format

        resp = self.client.chat.completions.create(**kwargs)
        return resp.choices[0].message.content

    def chat_json(
        self,
        messages: list[dict],
        temperature: float = 0.1,
        max_tokens: int = 4096,
    ) -> dict:
        """调用 Qwen 并解析 JSON 响应"""
        content = self.chat(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
        )
        return json.loads(content)

    def embed(self, text: str) -> list[float]:
        """
        使用 Qwen-Embedding 生成文本向量

        如果不可用则 fallback 到内置哈希向量。
        """
        try:
            resp = self.client.embeddings.create(
                model="text-embedding-v2",
                input=text,
            )
            return resp.data[0].embedding
        except Exception:
            # fallback: 简易哈希向量
            return self._fallback_embed(text)

    def _fallback_embed(self, text: str) -> list[float]:
        """简易哈希向量 fallback"""
        words = text.lower().split()
        unique = list(set(words))
        dim = settings.milvus_dimension
        vec = [0.0] * dim
        for i, word in enumerate(unique):
            if i >= dim:
                break
            idx = hash(word) % dim
            vec[idx] += 1.0
        norm = sum(v * v for v in vec) ** 0.5
        if norm > 0:
            vec = [v / norm for v in vec]
        return vec


# ============================================================
# Agent 基类
# ============================================================

class BaseAgent(ABC, Generic[T]):
    """Agent基类，提供通用功能 和 Qwen LLM 访问"""

    def __init__(self, name: AgentType, model: str = None):
        self.name = name
        self.timeout = settings.agent_timeout
        self._llm = QwenClient(model=model or self._default_model())

    def _default_model(self) -> str:
        """子类可覆盖以返回专用模型名"""
        return settings.qwen_model

    @property
    def llm(self) -> QwenClient:
        return self._llm

    @abstractmethod
    def process(self, state: SharedState) -> dict:
        """处理输入，返回要更新的状态"""
        pass

    def create_message(
        self,
        receiver: AgentType | None,
        content: str,
        metadata: dict = None,
    ) -> AgentMessage:
        """创建消息"""
        return AgentMessage(
            sender=self.name,
            receiver=receiver,
            content=content,
            timestamp=datetime.now(),
            metadata=metadata or {},
        )

    def log_start(self, state: SharedState) -> None:
        """记录开始时间"""
        if self.name.value not in state["agent_timestamps"]:
            state["agent_timestamps"][self.name.value] = {}
        state["agent_timestamps"][self.name.value]["start"] = datetime.now().isoformat()

    def log_end(self, state: SharedState) -> None:
        """记录结束时间"""
        if self.name.value in state["agent_timestamps"]:
            start = datetime.fromisoformat(
                state["agent_timestamps"][self.name.value]["start"]
            )
            duration = (datetime.now() - start).total_seconds()
            state["agent_timestamps"][self.name.value]["end"] = datetime.now().isoformat()
            state["agent_timestamps"][self.name.value]["duration"] = duration

    def add_error(self, state: SharedState, error: str) -> None:
        """记录错误"""
        state["agent_errors"][self.name.value] = error

    @staticmethod
    def format_result(result: dict) -> str:
        """格式化结果为JSON字符串"""
        return json.dumps(result, ensure_ascii=False, indent=2)

    def build_prompt(
        self,
        system_prompt: str,
        user_prompt: str,
    ) -> list[dict]:
        """构建 Qwen 标准消息格式"""
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]


class AgentRegistry:
    """Agent注册器"""
    _agents: dict[AgentType, BaseAgent] = {}

    @classmethod
    def register(cls, agent_type: AgentType, agent: BaseAgent):
        cls._agents[agent_type] = agent

    @classmethod
    def get(cls, agent_type: AgentType) -> BaseAgent:
        return cls._agents.get(agent_type)

    @classmethod
    def get_all(cls) -> dict[AgentType, BaseAgent]:
        return cls._agents.copy()
