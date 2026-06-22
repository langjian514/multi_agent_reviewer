"""可观测性模块 - 全链路追踪"""
import json
import time
from typing import Any, Optional
from dataclasses import dataclass, field, asdict
from datetime import datetime
from contextvars import ContextVar
from enum import Enum
import os


class TraceStatus(Enum):
    """追踪状态"""
    STARTED = "started"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class Span:
    """追踪跨度"""
    name: str
    span_id: str
    parent_id: str | None
    trace_id: str
    start_time: str
    end_time: str | None
    status: TraceStatus
    attributes: dict
    events: list[dict]
    duration_ms: float | None
    
    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Trace:
    """追踪记录"""
    trace_id: str
    name: str
    start_time: str
    end_time: str | None
    status: TraceStatus
    spans: list[Span]
    attributes: dict
    
    def to_dict(self) -> dict:
        return {
            "trace_id": self.trace_id,
            "name": self.name,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "status": self.status.value,
            "attributes": self.attributes,
            "spans": [s.to_dict() for s in self.spans]
        }


class Tracer:
    """
    追踪器 - 实现全链路追踪
    
    功能:
    1. 记录每个Agent的输入输出
    2. 记录耗时和token消耗
    3. 支持结构化日志
    4. 可导出到LangSmith或自建Trace系统
    """
    
    _current_trace: ContextVar[Optional[Trace]] = ContextVar('current_trace', default=None)
    _current_span: ContextVar[Optional[Span]] = ContextVar('current_span', default=None)
    
    def __init__(self, service_name: str = "multi_agent_reviewer"):
        self.service_name = service_name
        self.traces: list[Trace] = []
        self.output_dir = "./data/traces"
        
        # 确保输出目录存在
        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir, exist_ok=True)
    
    def start_trace(self, name: str, trace_id: str = None, attributes: dict = None) -> str:
        """开始追踪"""
        trace_id = trace_id or self._generate_id()
        
        trace = Trace(
            trace_id=trace_id,
            name=name,
            start_time=datetime.now().isoformat(),
            end_time=None,
            status=TraceStatus.STARTED,
            spans=[],
            attributes=attributes or {}
        )
        
        self.traces.append(trace)
        self._current_trace.set(trace)
        
        return trace_id
    
    def end_trace(self, trace_id: str = None, status: TraceStatus = TraceStatus.COMPLETED) -> None:
        """结束追踪"""
        trace = self._current_trace.get()
        if not trace:
            return
        
        trace.end_time = datetime.now().isoformat()
        trace.status = status
        self._current_trace.set(None)
    
    def start_span(
        self,
        name: str,
        parent_id: str = None,
        attributes: dict = None
    ) -> str:
        """开始跨度"""
        trace = self._current_trace.get()
        if not trace:
            return None
        
        span_id = self._generate_id()
        
        span = Span(
            name=name,
            span_id=span_id,
            parent_id=parent_id,
            trace_id=trace.trace_id,
            start_time=datetime.now().isoformat(),
            end_time=None,
            status=TraceStatus.RUNNING,
            attributes=attributes or {},
            events=[],
            duration_ms=None
        )
        
        trace.spans.append(span)
        self._current_span.set(span)
        
        return span_id
    
    def end_span(
        self,
        span_id: str = None,
        status: TraceStatus = TraceStatus.COMPLETED,
        attributes: dict = None
    ) -> None:
        """结束跨度"""
        span = self._current_span.get()
        if not span:
            return
        
        span.end_time = datetime.now().isoformat()
        span.status = status
        
        # 计算耗时
        start = datetime.fromisoformat(span.start_time)
        end = datetime.fromisoformat(span.end_time)
        span.duration_ms = (end - start).total_seconds() * 1000
        
        if attributes:
            span.attributes.update(attributes)
        
        self._current_span.set(None)
    
    def add_span_event(self, name: str, attributes: dict = None) -> None:
        """添加跨度事件"""
        span = self._current_span.get()
        if not span:
            return
        
        span.events.append({
            "name": name,
            "timestamp": datetime.now().isoformat(),
            "attributes": attributes or {}
        })
    
    def add_span_attribute(self, key: str, value: Any) -> None:
        """添加跨度属性"""
        span = self._current_span.get()
        if not span:
            return
        
        span.attributes[key] = value
    
    def record_agent_execution(
        self,
        agent_name: str,
        input_data: dict,
        output_data: dict,
        token_usage: dict = None,
        error: str = None
    ) -> None:
        """记录Agent执行"""
        span = self._current_span.get()
        if not span:
            return
        
        event_data = {
            "agent": agent_name,
            "input_keys": list(input_data.keys()) if isinstance(input_data, dict) else [],
            "output_keys": list(output_data.keys()) if isinstance(output_data, dict) else [],
            "has_error": error is not None
        }
        
        if token_usage:
            event_data["token_usage"] = token_usage
        
        if error:
            event_data["error"] = error
        
        span.events.append({
            "name": "agent_execution",
            "timestamp": datetime.now().isoformat(),
            "attributes": event_data
        })
    
    def export_trace(self, trace_id: str = None, format: str = "json") -> str:
        """导出追踪记录"""
        if trace_id:
            traces = [t for t in self.traces if t.trace_id == trace_id]
        else:
            traces = self.traces
        
        if format == "json":
            output = json.dumps([t.to_dict() for t in traces], indent=2, ensure_ascii=False)
        elif format == "compact":
            output = json.dumps([t.to_dict() for t in traces], ensure_ascii=False)
        else:
            output = str(traces)
        
        return output
    
    def save_trace(self, trace_id: str = None) -> str:
        """保存追踪记录到文件"""
        output = self.export_trace(trace_id, format="compact")
        
        filename = f"{self.output_dir}/{trace_id or 'trace'}_{int(time.time())}.json"
        with open(filename, "w", encoding="utf-8") as f:
            f.write(output)
        
        return filename
    
    def get_summary(self) -> dict:
        """获取追踪摘要"""
        total_traces = len(self.traces)
        completed = len([t for t in self.traces if t.status == TraceStatus.COMPLETED])
        failed = len([t for t in self.traces if t.status == TraceStatus.FAILED])
        
        total_spans = sum(len(t.spans) for t in self.traces)
        total_duration = sum(
            sum(s.duration_ms or 0 for s in t.spans)
            for t in self.traces
        )
        
        return {
            "total_traces": total_traces,
            "completed": completed,
            "failed": failed,
            "total_spans": total_spans,
            "total_duration_ms": total_duration,
            "avg_span_duration_ms": total_duration / total_spans if total_spans > 0 else 0
        }
    
    @staticmethod
    def _generate_id() -> str:
        """生成唯一ID"""
        import uuid
        return str(uuid.uuid4())[:16]


class AgentMetrics:
    """
    Agent指标收集
    
    收集:
    1. 执行次数
    2. 成功率
    3. 平均耗时
    4. Token消耗
    """
    
    def __init__(self):
        self.metrics: dict[str, dict] = {}
    
    def record(
        self,
        agent_name: str,
        success: bool,
        duration_ms: float,
        tokens_used: int = 0,
        error: str = None
    ) -> None:
        """记录指标"""
        if agent_name not in self.metrics:
            self.metrics[agent_name] = {
                "total_calls": 0,
                "successful_calls": 0,
                "failed_calls": 0,
                "total_duration_ms": 0,
                "total_tokens": 0,
                "errors": []
            }
        
        m = self.metrics[agent_name]
        m["total_calls"] += 1
        
        if success:
            m["successful_calls"] += 1
        else:
            m["failed_calls"] += 1
            if error:
                m["errors"].append(error)
        
        m["total_duration_ms"] += duration_ms
        m["total_tokens"] += tokens_used
    
    def get_metrics(self, agent_name: str = None) -> dict:
        """获取指标"""
        if agent_name:
            return self._calculate_metrics(agent_name)
        
        return {
            name: self._calculate_metrics(name)
            for name in self.metrics
        }
    
    def _calculate_metrics(self, agent_name: str) -> dict:
        """计算指标"""
        if agent_name not in self.metrics:
            return {}
        
        m = self.metrics[agent_name]
        total = m["total_calls"]
        
        return {
            "total_calls": total,
            "success_rate": m["successful_calls"] / total if total > 0 else 0,
            "avg_duration_ms": m["total_duration_ms"] / total if total > 0 else 0,
            "total_tokens": m["total_tokens"],
            "avg_tokens": m["total_tokens"] / total if total > 0 else 0,
            "recent_errors": m["errors"][-5:]  # 最近5个错误
        }


# 全局追踪器
_tracer: Tracer = None
_metrics: AgentMetrics = None


def get_tracer() -> Tracer:
    """获取追踪器"""
    global _tracer
    if _tracer is None:
        _tracer = Tracer()
    return _tracer


def get_metrics() -> AgentMetrics:
    """获取指标收集器"""
    global _metrics
    if _metrics is None:
        _metrics = AgentMetrics()
    return _metrics
