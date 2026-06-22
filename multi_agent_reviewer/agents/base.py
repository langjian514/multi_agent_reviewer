"""Agent基类"""
from abc import ABC, abstractmethod
from typing import TypeVar, Generic
from datetime import datetime
import json

from core.state import SharedState, AgentType, AgentMessage
from config.settings import settings


T = TypeVar('T')


class BaseAgent(ABC, Generic[T]):
    """Agent基类，提供通用功能"""
    
    def __init__(self, name: AgentType, model: str = "gpt-4"):
        self.name = name
        self.model = model
        self.timeout = settings.agent_timeout
    
    @abstractmethod
    def process(self, state: SharedState) -> dict:
        """处理输入，返回要更新的状态"""
        pass
    
    def create_message(
        self,
        receiver: AgentType | None,
        content: str,
        metadata: dict = None
    ) -> AgentMessage:
        """创建消息"""
        return AgentMessage(
            sender=self.name,
            receiver=receiver,
            content=content,
            timestamp=datetime.now(),
            metadata=metadata or {}
        )
    
    def log_start(self, state: SharedState) -> None:
        """记录开始时间"""
        if self.name.value not in state["agent_timestamps"]:
            state["agent_timestamps"][self.name.value] = {}
        state["agent_timestamps"][self.name.value]["start"] = datetime.now().isoformat()
    
    def log_end(self, state: SharedState) -> None:
        """记录结束时间"""
        if self.name.value in state["agent_timestamps"]:
            start = datetime.fromisoformat(state["agent_timestamps"][self.name.value]["start"])
            duration = (datetime.now() - start).total_seconds()
            state["agent_timestamps"][self.name.value]["end"] = datetime.now().isoformat()
            state["agent_timestamps"][self.name.value]["duration"] = duration
    
    def add_error(self, state: SharedState, error: str) -> None:
        """记录错误"""
        state["agent_errors"][self.name.value] = error
    
    def format_result(self, result: dict) -> str:
        """格式化结果为JSON字符串"""
        return json.dumps(result, ensure_ascii=False, indent=2)


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
