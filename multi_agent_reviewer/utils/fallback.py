"""降级容错模块"""
import asyncio
from typing import TypeVar, Generic, Callable, Any
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from functools import wraps
import traceback

from config.settings import settings


class FallbackType(Enum):
    """降级类型"""
    TIMEOUT = "timeout"
    ERROR = "error"
    CIRCUIT_BREAK = "circuit_breaker"
    RATE_LIMIT = "rate_limit"
    EMPTY_RESULT = "empty_result"


@dataclass
class FallbackResult:
    """降级结果"""
    success: bool
    result: Any
    fallback_used: bool
    error: str | None
    fallback_type: FallbackType | None
    duration: float


class CircuitBreaker:
    """
    熔断器 - 防止级联失败
    
    状态:
    - CLOSED: 正常状态
    - OPEN: 熔断状态，后续请求直接降级
    - HALF_OPEN: 半开状态，尝试恢复
    """
    
    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        half_open_attempts: int = 3
    ):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_attempts = half_open_attempts
        
        self.failures = 0
        self.last_failure_time: datetime | None = None
        self.state = "CLOSED"
        self.half_open_successes = 0
    
    def record_success(self) -> None:
        """记录成功"""
        if self.state == "HALF_OPEN":
            self.half_open_successes += 1
            if self.half_open_successes >= self.half_open_attempts:
                self._reset()
        elif self.state == "CLOSED":
            self.failures = 0
    
    def record_failure(self) -> None:
        """记录失败"""
        self.failures += 1
        self.last_failure_time = datetime.now()
        
        if self.state == "HALF_OPEN":
            self._trip()
        elif self.failures >= self.failure_threshold:
            self._trip()
    
    def _trip(self) -> None:
        """打开熔断器"""
        self.state = "OPEN"
        self.half_open_successes = 0
    
    def _reset(self) -> None:
        """重置熔断器"""
        self.state = "CLOSED"
        self.failures = 0
        self.half_open_successes = 0
    
    def can_execute(self) -> bool:
        """是否可以执行"""
        if self.state == "CLOSED":
            return True
        
        if self.state == "OPEN":
            if self.last_failure_time:
                elapsed = (datetime.now() - self.last_failure_time).total_seconds()
                if elapsed >= self.recovery_timeout:
                    self.state = "HALF_OPEN"
                    return True
            return False
        
        # HALF_OPEN
        return True


T = TypeVar('T')


class FallbackManager:
    """
    降级管理器
    
    功能:
    1. 超时中断
    2. 结果兜底
    3. 熔断器模式
    4. 重试机制
    """
    
    def __init__(self):
        self.circuit_breakers: dict[str, CircuitBreaker] = {}
        self.fallback_strategies: dict[str, Callable] = {}
    
    def get_circuit_breaker(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0
    ) -> CircuitBreaker:
        """获取或创建熔断器"""
        if name not in self.circuit_breakers:
            self.circuit_breakers[name] = CircuitBreaker(
                failure_threshold=failure_threshold,
                recovery_timeout=recovery_timeout
            )
        return self.circuit_breakers[name]
    
    def register_fallback(
        self,
        agent_type: str,
        fallback_fn: Callable[[], Any]
    ) -> None:
        """注册降级策略"""
        self.fallback_strategies[agent_type] = fallback_fn
    
    async def execute_with_fallback(
        self,
        name: str,
        primary_fn: Callable,
        fallback_fn: Callable | None = None,
        args: tuple = (),
        kwargs: dict = None,
        timeout: float = None,
        circuit_breaker: str = None
    ) -> FallbackResult:
        """
        执行带降级的操作
        
        Args:
            name: 操作名称
            primary_fn: 主函数
            fallback_fn: 降级函数
            args: 位置参数
            kwargs: 关键字参数
            timeout: 超时时间
            circuit_breaker: 熔断器名称
        """
        kwargs = kwargs or {}
        start_time = datetime.now()
        
        # 检查熔断器
        cb = None
        if circuit_breaker:
            cb = self.get_circuit_breaker(circuit_breaker)
            if not cb.can_execute():
                return FallbackResult(
                    success=False,
                    result=None,
                    fallback_used=True,
                    error="Circuit breaker open",
                    fallback_type=FallbackType.CIRCUIT_BREAK,
                    duration=(datetime.now() - start_time).total_seconds()
                )
        
        # 获取降级函数
        fallback_fn = fallback_fn or self.fallback_strategies.get(name)
        
        try:
            # 设置超时
            timeout = timeout or settings.agent_timeout
            
            # 执行主函数
            if asyncio.iscoroutinefunction(primary_fn):
                result = await asyncio.wait_for(
                    primary_fn(*args, **kwargs),
                    timeout=timeout
                )
            else:
                result = await asyncio.wait_for(
                    asyncio.to_thread(primary_fn, *args, **kwargs),
                    timeout=timeout
                )
            
            # 检查结果是否有效
            if result is None or (isinstance(result, dict) and not result):
                if fallback_fn:
                    return FallbackResult(
                        success=False,
                        result=fallback_fn(),
                        fallback_used=True,
                        error="Empty result",
                        fallback_type=FallbackType.EMPTY_RESULT,
                        duration=(datetime.now() - start_time).total_seconds()
                    )
            
            # 记录成功
            if cb:
                cb.record_success()
            
            return FallbackResult(
                success=True,
                result=result,
                fallback_used=False,
                error=None,
                fallback_type=None,
                duration=(datetime.now() - start_time).total_seconds()
            )
        
        except asyncio.TimeoutError:
            if cb:
                cb.record_failure()
            
            if fallback_fn:
                return FallbackResult(
                    success=False,
                    result=fallback_fn(),
                    fallback_used=True,
                    error=f"Timeout after {timeout}s",
                    fallback_type=FallbackType.TIMEOUT,
                    duration=(datetime.now() - start_time).total_seconds()
                )
            
            return FallbackResult(
                success=False,
                result=None,
                fallback_used=True,
                error=f"Timeout after {timeout}s",
                fallback_type=FallbackType.TIMEOUT,
                duration=(datetime.now() - start_time).total_seconds()
            )
        
        except Exception as e:
            if cb:
                cb.record_failure()
            
            error_msg = f"{type(e).__name__}: {str(e)}"
            
            if fallback_fn:
                try:
                    if asyncio.iscoroutinefunction(fallback_fn):
                        fb_result = await fallback_fn()
                    else:
                        fb_result = fallback_fn()
                    
                    return FallbackResult(
                        success=False,
                        result=fb_result,
                        fallback_used=True,
                        error=error_msg,
                        fallback_type=FallbackType.ERROR,
                        duration=(datetime.now() - start_time).total_seconds()
                    )
                except Exception:
                    pass
            
            return FallbackResult(
                success=False,
                result=None,
                fallback_used=True,
                error=error_msg,
                fallback_type=FallbackType.ERROR,
                duration=(datetime.now() - start_time).total_seconds()
            )


def with_fallback(
    fallback_fn: Callable = None,
    timeout: float = None,
    circuit_breaker: str = None
):
    """装饰器：为函数添加降级能力"""
    def decorator(fn: Callable) -> Callable:
        @wraps(fn)
        async def wrapper(*args, **kwargs):
            manager = get_fallback_manager()
            return await manager.execute_with_fallback(
                name=fn.__name__,
                primary_fn=fn,
                fallback_fn=fallback_fn,
                args=args,
                kwargs=kwargs,
                timeout=timeout,
                circuit_breaker=circuit_breaker
            )
        return wrapper
    return decorator


# 内置降级策略

def analyzer_fallback() -> dict:
    """分析Agent降级策略"""
    return {
        "code_structure": {"total_lines": 0, "code_lines": 0, "functions": [], "classes": []},
        "complexity_score": 5.0,
        "key_functions": [],
        "dependencies": [],
        "issues": [{"type": "analysis_failed", "severity": "warning", "message": "分析超时"}]
    }


def security_fallback() -> dict:
    """安全Agent降级策略"""
    return {
        "vulnerabilities": [],
        "sql_injection_risks": [],
        "xss_risks": [],
        "other_risks": [{"type": "scan_failed", "severity": "info", "message": "安全扫描超时"}],
        "severity_counts": {"critical": 0, "high": 0, "medium": 0, "low": 0}
    }


def linter_fallback() -> dict:
    """规范Agent降级策略"""
    return {
        "style_violations": [],
        "naming_issues": [],
        "error_handling_issues": [],
        "best_practices": [],
        "suggestion": "规范检查超时"
    }


def reviewer_fallback() -> dict:
    """总结Agent降级策略"""
    return {
        "summary": "审查过程遇到问题，建议人工复查",
        "all_issues": [],
        "critical_issues": [],
        "warnings": [{"type": "review_failed", "message": "总结生成超时"}],
        "suggestions": ["请人工审查代码"],
        "quality_score": 0.0,
        "confidence": 0.0
    }


# 全局降级管理器
_fallback_manager: FallbackManager = None


def get_fallback_manager() -> FallbackManager:
    """获取降级管理器"""
    global _fallback_manager
    if _fallback_manager is None:
        _fallback_manager = FallbackManager()
        # 注册默认降级策略
        _fallback_manager.register_fallback("analyzer", analyzer_fallback)
        _fallback_manager.register_fallback("security", security_fallback)
        _fallback_manager.register_fallback("linter", linter_fallback)
        _fallback_manager.register_fallback("reviewer", reviewer_fallback)
    return _fallback_manager
