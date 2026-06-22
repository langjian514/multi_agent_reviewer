"""LangGraph状态机编排器"""
import asyncio
from typing import Literal
from datetime import datetime
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from core.state import SharedState, ReviewState, AgentType, create_initial_state
from agents import register_all_agents, get_agent
from config.settings import settings


class Orchestrator:
    """
    编排器 - 使用LangGraph状态机协调多个Agent
    
    为什么用状态机而非链式调用？
    1. 状态机支持条件分支 - 根据Agent结果决定下一步
    2. 状态机支持循环 - 自反思模块可以重新分配任务
    3. 状态机支持并行 - 多个独立Agent可以并行执行
    4. 状态机可观测性强 - 每个节点的状态转换清晰可追踪
    """
    
    def __init__(self):
        register_all_agents()
        self.checkpointer = MemorySaver()
        self.graph = self._build_graph()
    
    def _build_graph(self) -> StateGraph:
        """构建状态图"""
        graph = StateGraph(SharedState)
        
        # 添加节点
        graph.add_node("orchestrator", self._orchestrator_node)
        graph.add_node("analyzer", self._analyzer_node)
        graph.add_node("security", self._security_node)
        graph.add_node("linter", self._linter_node)
        graph.add_node("reviewer", self._reviewer_node)
        graph.add_node("reflection", self._reflection_node)
        graph.add_node("finalize", self._finalize_node)
        
        # 设置入口
        graph.set_entry_point("orchestrator")
        
        # 定义边和条件分支
        graph.add_edge("orchestrator", "analyzer")
        graph.add_edge("analyzer", "security")
        graph.add_edge("security", "linter")
        graph.add_edge("linter", "reviewer")
        graph.add_edge("reviewer", "reflection")
        
        # 自反思节点：根据质量决定是重试还是结束
        graph.add_conditional_edges(
            "reflection",
            self._should_retry,
            {
                "retry": "orchestrator",  # 质量不达标，重新开始
                "finalize": "finalize"     # 质量达标，输出结果
            }
        )
        
        # 结束
        graph.add_edge("finalize", END)
        
        return graph.compile(checkpointer=self.checkpointer)
    
    async def _orchestrator_node(self, state: SharedState) -> dict:
        """编排节点 - 负责任务分配和协调"""
        state["status"] = ReviewState.RECEIVED
        state["current_agent"] = AgentType.ORCHESTRATOR
        
        # 如果是重试，增加计数
        if state.get("needs_retry"):
            state["reflection_count"] = state.get("reflection_count", 0) + 1
            state["needs_retry"] = False
            state["retry_reason"] = None
        
        return state
    
    async def _analyzer_node(self, state: SharedState) -> dict:
        """分析节点"""
        agent = get_agent(AgentType.ANALYZER)
        result = agent.process(state)
        return result
    
    async def _security_node(self, state: SharedState) -> dict:
        """安全扫描节点"""
        agent = get_agent(AgentType.SECURITY)
        result = agent.process(state)
        return result
    
    async def _linter_node(self, state: SharedState) -> dict:
        """规范检查节点"""
        agent = get_agent(AgentType.LINTER)
        result = agent.process(state)
        return result
    
    async def _reviewer_node(self, state: SharedState) -> dict:
        """总结节点"""
        agent = get_agent(AgentType.REVIEWER)
        result = agent.process(state)
        return result
    
    async def _reflection_node(self, state: SharedState) -> dict:
        """
        自反思节点 - 评估输出质量
        
        终止条件：
        1. 质量评分 >= 阈值 (默认0.7)
        2. 超过最大重试次数 (默认3次)
        3. 无critical问题
        """
        state["status"] = ReviewState.REFLECTING
        
        report = state.get("review_report")
        if not report:
            state["quality_score"] = 0.0
            state["quality_passed"] = False
            state["needs_retry"] = True
            state["retry_reason"] = "No review report generated"
            return state
        
        # 评估质量
        quality_score = report.get("quality_score", 0.0)
        confidence = report.get("confidence", 0.0)
        critical = report.get("critical_issues", [])
        
        state["quality_score"] = quality_score
        state["quality_assesed"] = True
        
        # 质量达标条件
        no_critical = len(critical) == 0
        sufficient_quality = quality_score >= settings.min_quality_score
        sufficient_confidence = confidence >= 0.5
        within_retries = state.get("reflection_count", 0) < settings.max_retries
        
        if no_critical and sufficient_quality and sufficient_confidence and within_retries:
            state["quality_passed"] = True
            state["needs_retry"] = False
        else:
            state["quality_passed"] = False
            
            if not no_critical:
                state["retry_reason"] = f"存在{len(critical)}个严重问题"
            elif not sufficient_quality:
                state["retry_reason"] = f"质量评分不足 ({quality_score} < {settings.min_quality_score})"
            elif not sufficient_confidence:
                state["retry_reason"] = f"置信度过低 ({confidence})"
            else:
                state["retry_reason"] = "超过最大重试次数"
            
            state["needs_retry"] = True
        
        return state
    
    def _should_retry(self, state: SharedState) -> Literal["retry", "finalize"]:
        """判断是否需要重试"""
        if state.get("needs_retry") and state.get("reflection_count", 0) < settings.max_retries:
            return "retry"
        return "finalize"
    
    async def _finalize_node(self, state: SharedState) -> dict:
        """最终输出节点"""
        state["status"] = ReviewState.DONE
        state["current_agent"] = None
        return state
    
    async def execute(self, code: str, task_id: str = None, language: str = "python") -> SharedState:
        """
        执行审查流程
        
        Args:
            code: 要审查的代码
            task_id: 任务ID
            language: 代码语言
        
        Returns:
            最终状态
        """
        task_id = task_id or f"task_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        # 创建初始状态
        initial_state = create_initial_state(
            code=code,
            task_id=task_id,
            language=language
        )
        
        # 运行图
        config = {"configurable": {"thread_id": task_id}}
        
        try:
            result = await asyncio.wait_for(
                self.graph.ainvoke(initial_state, config=config),
                timeout=settings.total_timeout
            )
            return result
        except asyncio.TimeoutError:
            # 超时处理
            initial_state["status"] = ReviewState.FAILED
            initial_state["agent_errors"]["timeout"] = f"任务超时 (>{settings.total_timeout}s)"
            return initial_state


# 全局单例
_orchestrator: Orchestrator = None


def get_orchestrator() -> Orchestrator:
    """获取编排器单例"""
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = Orchestrator()
    return _orchestrator
