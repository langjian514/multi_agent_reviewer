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
        self.subscriptions: dict[str, set[str]] = {}  # task_id -> set of websocket_ids
    
    async def connect(self, websocket: WebSocket, client_id: str) -> None:
        """连接"""
        await websocket.accept()
        self.active_connections[client_id] = websocket
    
    def disconnect(self, client_id: str) -> None:
        """断开连接"""
        if client_id in self.active_connections:
            del self.active_connections[client_id]
        
        # 清理订阅
        for task_id in self.subscriptions:
            self.subscriptions[task_id].discard(client_id)
    
    async def send_message(self, client_id: str, message: dict) -> None:
        """发送消息"""
        if client_id in self.active_connections:
            websocket = self.active_connections[client_id]
            try:
                await websocket.send_json(message)
            except Exception:
                self.disconnect(client_id)
    
    async def broadcast(self, task_id: str, message: dict) -> None:
        """广播消息"""
        if task_id in self.subscriptions:
            for client_id in self.subscriptions[task_id]:
                await self.send_message(client_id, message)
    
    def subscribe(self, task_id: str, client_id: str) -> None:
        """订阅任务"""
        if task_id not in self.subscriptions:
            self.subscriptions[task_id] = set()
        self.subscriptions[task_id].add(client_id)
    
    def unsubscribe(self, task_id: str, client_id: str) -> None:
        """取消订阅"""
        if task_id in self.subscriptions:
            self.subscriptions[task_id].discard(client_id)


# 全局连接管理器
manager = ConnectionManager()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期"""
    # 启动时
    print("Multi-Agent Code Reviewer API starting...")
    yield
    # 关闭时
    print("Multi-Agent Code Reviewer API shutting down...")


app = FastAPI(
    title="Multi-Agent Code Reviewer",
    description="智能代码审查助手 - 基于多智能体协作",
    version="1.0.0",
    lifespan=lifespan
)


@app.get("/")
async def root():
    """根路径"""
    return {
        "service": "Multi-Agent Code Reviewer",
        "version": "1.0.0",
        "status": "running"
    }


@app.get("/health")
async def health():
    """健康检查"""
    return {"status": "healthy"}


@app.post("/api/review", response_model=ReviewResponse)
async def create_review(request: ReviewRequest, background_tasks: BackgroundTasks):
    """
    创建代码审查任务
    
    支持同步和异步两种模式：
    - 如果提供了websocket_id，则通过WebSocket实时推送结果
    - 否则返回任务ID，可通过GET /api/review/{task_id}查询结果
    """
    task_id = request.task_id or f"task_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    
    # 如果有WebSocket订阅，先发送初始状态
    if request.websocket_id:
        manager.subscribe(task_id, request.websocket_id)
        await manager.send_message(request.websocket_id, {
            "type": "task_started",
            "data": {"task_id": task_id, "status": "pending"},
            "timestamp": datetime.now().isoformat()
        })
    
    # 启动后台审查任务
    background_tasks.add_task(
        run_review_task,
        task_id,
        request.code,
        request.language
    )
    
    return ReviewResponse(
        task_id=task_id,
        status="pending",
        message="Review task created"
    )


async def run_review_task(task_id: str, code: str, language: str):
    """运行审查任务"""
    orchestrator = get_orchestrator()
    tracer = get_tracer()
    
    # 开始追踪
    trace_id = tracer.start_trace(
        name=f"review_{task_id}",
        trace_id=task_id,
        attributes={"language": language}
    )
    
    try:
        # 广播开始
        await manager.broadcast(task_id, {
            "type": "status_update",
            "data": {"status": "analyzing"},
            "timestamp": datetime.now().isoformat()
        })
        
        # 执行审查
        result = await orchestrator.execute(
            code=code,
            task_id=task_id,
            language=language
        )
        
        # 广播结果
        await manager.broadcast(task_id, {
            "type": "review_completed",
            "data": {
                "task_id": task_id,
                "status": result["status"].value if isinstance(result["status"], ReviewState) else result["status"],
                "quality_score": result.get("review_report", {}).get("quality_score", 0),
                "confidence": result.get("review_report", {}).get("confidence", 0)
            },
            "timestamp": datetime.now().isoformat()
        })
        
        tracer.end_trace(trace_id, status="completed" if result["status"] == ReviewState.DONE else "failed")
        
    except Exception as e:
        await manager.broadcast(task_id, {
            "type": "error",
            "data": {"error": str(e)},
            "timestamp": datetime.now().isoformat()
        })
        tracer.end_trace(trace_id, status="failed")


@app.get("/api/review/{task_id}")
async def get_review_status(task_id: str):
    """获取审查状态"""
    # TODO: 从存储中获取任务状态
    return {
        "task_id": task_id,
        "status": "completed"
    }


@app.get("/api/review/{task_id}/report")
async def get_review_report(task_id: str):
    """获取审查报告"""
    # TODO: 从存储中获取报告
    return {
        "task_id": task_id,
        "report": {}
    }


@app.get("/api/agents")
async def list_agents():
    """列出所有Agent"""
    from agents import get_all_agents
    from core.state import AgentType
    
    agents = get_all_agents()
    return {
        "agents": [
            {"type": agent_type.value, "name": agent_type.value}
            for agent_type in agents.keys()
        ]
    }


@app.get("/api/tools")
async def list_tools():
    """列出所有可用工具"""
    from tools.mcp import get_mcp_server
    
    mcp_server = get_mcp_server()
    return {
        "tools": mcp_server.discover_tools()
    }


@app.get("/api/metrics")
async def get_metrics():
    """获取系统指标"""
    from utils.trace import get_metrics, get_tracer
    
    return {
        "tracer_summary": get_tracer().get_summary(),
        "agent_metrics": get_metrics().get_metrics()
    }


@app.websocket("/ws/{client_id}")
async def websocket_endpoint(websocket: WebSocket, client_id: str):
    """
    WebSocket端点 - 实时接收审查进度更新
    
    消息类型:
    - task_started: 任务开始
    - status_update: 状态更新
    - review_completed: 审查完成
    - error: 错误
    """
    await manager.connect(websocket, client_id)
    
    try:
        while True:
            # 接收客户端消息
            data = await websocket.receive_json()
            
            # 处理订阅请求
            if data.get("type") == "subscribe":
                task_id = data.get("task_id")
                if task_id:
                    manager.subscribe(task_id, client_id)
                    await manager.send_message(client_id, {
                        "type": "subscribed",
                        "data": {"task_id": task_id},
                        "timestamp": datetime.now().isoformat()
                    })
            
            # 处理取消订阅
            elif data.get("type") == "unsubscribe":
                task_id = data.get("task_id")
                if task_id:
                    manager.unsubscribe(task_id, client_id)
            
            # 处理心跳
            elif data.get("type") == "ping":
                await manager.send_message(client_id, {
                    "type": "pong",
                    "data": {},
                    "timestamp": datetime.now().isoformat()
                })
    
    except WebSocketDisconnect:
        manager.disconnect(client_id)
    except Exception as e:
        manager.disconnect(client_id)


def start_server(host: str = "0.0.0.0", port: int = 8000):
    """启动服务器"""
    uvicorn.run(
        "api.main:app",
        host=host,
        port=port,
        reload=False,
        log_level="info"
    )


if __name__ == "__main__":
    start_server()
