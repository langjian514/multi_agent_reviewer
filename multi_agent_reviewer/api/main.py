"""FastAPI后端 + WebSocket实时推送"""
import asyncio
import json
from datetime import datetime
from typing import Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
import uvicorn

from core.orchestrator import get_orchestrator
from core.state import SharedState, ReviewState
from memory.manager import get_memory_manager
from utils.trace import get_tracer


class ReviewRequest(BaseModel):
    """审查请求"""
    code: str = Field(..., description="要审查的代码")
    language: str = Field(default="python", description="代码语言")
    task_id: Optional[str] = Field(default=None, description="任务ID")
    websocket_id: Optional[str] = Field(default=None, description="WebSocket连接ID")


class ReviewResponse(BaseModel):
    """审查响应"""
    task_id: str
    status: str
    message: str


class WSMessage(BaseModel):
    """WebSocket消息"""
    type: str
    data: dict
    timestamp: str


class ConnectionManager:
    """WebSocket连接管理器"""
    def __init__(self):
        self.active_connections: dict[str, WebSocket] = {}
        self.subscriptions: dict[str, set[str]] = {}

    async def connect(self, websocket: WebSocket, client_id: str) -> None:
        await websocket.accept()
        self.active_connections[client_id] = websocket

    def disconnect(self, client_id: str) -> None:
        if client_id in self.active_connections:
            del self.active_connections[client_id]
        for task_id in list(self.subscriptions.keys()):
            self.subscriptions[task_id].discard(client_id)

    async def send_message(self, client_id: str, message: dict) -> None:
        if client_id in self.active_connections:
            try:
                await self.active_connections[client_id].send_json(message)
            except Exception:
                self.disconnect(client_id)

    async def broadcast(self, task_id: str, message: dict) -> None:
        if task_id in self.subscriptions:
            for client_id in list(self.subscriptions[task_id]):
                await self.send_message(client_id, message)

    def subscribe(self, task_id: str, client_id: str) -> None:
        if task_id not in self.subscriptions:
            self.subscriptions[task_id] = set()
        self.subscriptions[task_id].add(client_id)

    def unsubscribe(self, task_id: str, client_id: str) -> None:
        if task_id in self.subscriptions:
            self.subscriptions[task_id].discard(client_id)


manager = ConnectionManager()

# 内存结果存储（供 GET 接口轮询）
_review_store: dict[str, dict] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Multi-Agent Code Reviewer API starting...")
    yield
    print("Multi-Agent Code Reviewer API shutting down...")


app = FastAPI(
    title="Multi-Agent Code Reviewer",
    description="智能代码审查助手 - 基于多智能体协作",
    version="1.0.0",
    lifespan=lifespan
)


@app.get("/")
async def root():
    return {"service": "Multi-Agent Code Reviewer", "version": "1.0.0", "status": "running"}


@app.get("/health")
async def health():
    return {"status": "healthy"}


@app.post("/api/review", response_model=ReviewResponse)
async def create_review(request: ReviewRequest, background_tasks: BackgroundTasks):
    """创建代码审查任务，后台执行"""
    task_id = request.task_id or f"task_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    _review_store[task_id] = {"status": "pending", "report": None}

    if request.websocket_id:
        manager.subscribe(task_id, request.websocket_id)
        await manager.send_message(request.websocket_id, {
            "type": "task_started", "data": {"task_id": task_id, "status": "pending"},
            "timestamp": datetime.now().isoformat()
        })

    background_tasks.add_task(run_review_task, task_id, request.code, request.language)

    return ReviewResponse(task_id=task_id, status="pending", message="Review task created")


async def run_review_task(task_id: str, code: str, language: str):
    orchestrator = get_orchestrator()
    tracer = get_tracer()

    trace_id = tracer.start_trace(
        name=f"review_{task_id}", trace_id=task_id, attributes={"language": language}
    )

    try:
        await manager.broadcast(task_id, {
            "type": "status_update", "data": {"status": "analyzing"},
            "timestamp": datetime.now().isoformat()
        })

        result = await orchestrator.execute(code=code, task_id=task_id, language=language)

        # 存储结果供 GET 接口查询
        review_report = result.get("review_report") or {}
        _review_store[task_id] = {
            "status": "completed",
            "report": review_report,
            "full_result": {
                k: v for k, v in result.items()
                if k in ("analysis_result", "security_result", "lint_result", "review_report",
                         "quality_score", "agent_timestamps", "status")
            }
        }

        await manager.broadcast(task_id, {
            "type": "review_completed",
            "data": {
                "task_id": task_id,
                "status": result["status"].value if isinstance(result["status"], ReviewState) else result["status"],
                "quality_score": review_report.get("quality_score", 0),
                "confidence": review_report.get("confidence", 0)
            },
            "timestamp": datetime.now().isoformat()
        })

        tracer.end_trace(trace_id, status="completed")
    except Exception as e:
        _review_store[task_id] = {"status": "failed", "error": str(e), "report": None}
        await manager.broadcast(task_id, {
            "type": "error", "data": {"error": str(e)},
            "timestamp": datetime.now().isoformat()
        })
        tracer.end_trace(trace_id, status="failed")


@app.get("/api/review/{task_id}")
async def get_review_status(task_id: str):
    """获取审查状态"""
    result = _review_store.get(task_id)
    if not result:
        return {"task_id": task_id, "status": "unknown"}
    return {"task_id": task_id, "status": result.get("status", "unknown")}


@app.get("/api/review/{task_id}/report")
async def get_review_report(task_id: str):
    """获取审查报告"""
    result = _review_store.get(task_id)
    if not result:
        return {"task_id": task_id, "report": {}}
    report_data = result.get("report", {})
    full = result.get("full_result", {})
    timestamps = full.get("agent_timestamps", {})
    report_data["agent_timings"] = {
        agent: times.get("duration", 0)
        for agent, times in timestamps.items()
        if times.get("duration")
    }
    return {"task_id": task_id, "report": report_data}


@app.get("/api/agents")
async def list_agents():
    from agents import get_all_agents
    from core.state import AgentType
    agents = get_all_agents()
    return {"agents": [{"type": agent_type.value, "name": agent_type.value} for agent_type in agents.keys()]}


@app.get("/api/tools")
async def list_tools():
    from tools.mcp import get_mcp_server
    mcp_server = get_mcp_server()
    return {"tools": mcp_server.discover_tools()}


@app.get("/api/metrics")
async def get_metrics():
    from utils.trace import get_metrics, get_tracer
    return {"tracer_summary": get_tracer().get_summary(), "agent_metrics": get_metrics().get_metrics()}


@app.websocket("/ws/{client_id}")
async def websocket_endpoint(websocket: WebSocket, client_id: str):
    await manager.connect(websocket, client_id)
    try:
        while True:
            data = await websocket.receive_json()
            if data.get("type") == "subscribe":
                task_id = data.get("task_id")
                if task_id:
                    manager.subscribe(task_id, client_id)
                    await manager.send_message(client_id, {
                        "type": "subscribed", "data": {"task_id": task_id},
                        "timestamp": datetime.now().isoformat()
                    })
            elif data.get("type") == "unsubscribe":
                task_id = data.get("task_id")
                if task_id:
                    manager.unsubscribe(task_id, client_id)
            elif data.get("type") == "ping":
                await manager.send_message(client_id, {
                    "type": "pong", "data": {},
                    "timestamp": datetime.now().isoformat()
                })
    except WebSocketDisconnect:
        manager.disconnect(client_id)
    except Exception:
        manager.disconnect(client_id)


def start_server(host: str = "0.0.0.0", port: int = 8000):
    uvicorn.run("api.main:app", host=host, port=port, reload=False, log_level="info")


if __name__ == "__main__":
    start_server()

