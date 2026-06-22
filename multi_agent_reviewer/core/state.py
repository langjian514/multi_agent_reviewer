"""共享状态定义 - 多智能体协作的核心数据结构"""
from typing import TypedDict, Annotated, Optional, Any
from datetime import datetime
from enum import Enum
import operator


class TaskStatus(Enum):
    """任务状态"""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRYING = "retrying"


class AgentType(Enum):
    """Agent类型"""
    ORCHESTRATOR = "orchestrator"
    ANALYZER = "analyzer"
    SECURITY = "security"
    LINTER = "linter"
    REVIEWER = "reviewer"


class ReviewState(Enum):
    """审查状态"""
    RECEIVED = "received"           # 接收原始输入
    ANALYZING = "analyzing"         # 分析中
    SECURITY_SCANNING = "security_scanning"  # 安全扫描中
    LINTING = "linting"             # 规范检查中
    REVIEWING = "reviewing"         # 总结中
    REFLECTING = "reflecting"       # 自反思中
    FINALIZING = "finalizing"        # 最终输出
    DONE = "done"                   # 完成


class AgentMessage(TypedDict):
    """Agent间消息传递"""
    sender: AgentType
    receiver: AgentType | None  # None表示广播
    content: str
    timestamp: datetime
    metadata: dict


class AnalysisResult(TypedDict):
    """分析结果"""
    code_structure: dict
    complexity_score: float
    key_functions: list[str]
    dependencies: list[str]
    issues: list[dict]


class SecurityResult(TypedDict):
    """安全扫描结果"""
    vulnerabilities: list[dict]
    sql_injection_risks: list[dict]
    xss_risks: list[dict]
    other_risks: list[dict]
    severity_counts: dict


class LintResult(TypedDict):
    """规范检查结果"""
    style_violations: list[dict]
    naming_issues: list[dict]
    error_handling_issues: list[dict]
    best_practices: list[dict]
    suggestion: str


class ReviewReport(TypedDict):
    """最终审查报告"""
    summary: str
    all_issues: list[dict]
    critical_issues: list[dict]
    warnings: list[dict]
    suggestions: list[str]
    quality_score: float
    confidence: float


class SharedState(TypedDict):
    """
    共享状态 - 贯穿整个审查流程
    
    设计原则:
    1. 只共享必要信息，避免信息过载
    2. 每个Agent只更新自己负责的部分
    3. 使用Anotated提供默认值
    """
    # === 元信息 ===
    task_id: str
    created_at: datetime
    status: ReviewState
    current_agent: AgentType | None
    
    # === 原始输入 ===
    original_code: str
    language: str
    file_path: str | None
    
    # === 各Agent结果 ===
    analysis_result: AnalysisResult | None
    security_result: SecurityResult | None
    lint_result: LintResult | None
    review_report: ReviewReport | None
    
    # === 消息传递 ===
    messages: Annotated[list[AgentMessage], operator.add]
    
    # === 自反思相关 ===
    reflection_count: int
    quality_score: float | None
    needs_retry: bool
    retry_reason: str | None
    
    # === 降级容错 ===
    agent_errors: dict
    fallback_used: bool
    
    # === 可观测性 ===
    agent_timestamps: dict  # {agent: {start, end, duration}}
    token_usage: dict
    
    # === 质量评估 ===
    quality_assesed: bool
    quality_passed: bool


def create_initial_state(
    code: str,
    task_id: str,
    language: str = "python",
    file_path: str | None = None
) -> SharedState:
    """创建初始状态"""
    return SharedState(
        task_id=task_id,
        created_at=datetime.now(),
        status=ReviewState.RECEIVED,
        current_agent=None,
        original_code=code,
        language=language,
        file_path=file_path,
        analysis_result=None,
        security_result=None,
        lint_result=None,
        review_report=None,
        messages=[],
        reflection_count=0,
        quality_score=None,
        needs_retry=False,
        retry_reason=None,
        agent_errors={},
        fallback_used=False,
        agent_timestamps={},
        token_usage={},
        quality_assesed=False,
        quality_passed=False,
    )
