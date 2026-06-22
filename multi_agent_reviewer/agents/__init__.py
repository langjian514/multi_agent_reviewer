"""Agent初始化"""
from agents.base import BaseAgent, AgentRegistry
from agents.analyzer import AnalyzerAgent
from agents.security import SecurityAgent
from agents.linter import LinterAgent
from agents.reviewer import ReviewerAgent
from core.state import AgentType


def register_all_agents():
    """注册所有Agent"""
    agents = [
        (AgentType.ANALYZER, AnalyzerAgent()),
        (AgentType.SECURITY, SecurityAgent()),
        (AgentType.LINTER, LinterAgent()),
        (AgentType.REVIEWER, ReviewerAgent()),
    ]
    
    for agent_type, agent in agents:
        AgentRegistry.register(agent_type, agent)


def get_agent(agent_type: AgentType) -> BaseAgent:
    """获取指定类型的Agent"""
    return AgentRegistry.get(agent_type)


def get_all_agents() -> dict[AgentType, BaseAgent]:
    """获取所有已注册的Agent"""
    return AgentRegistry.get_all()
