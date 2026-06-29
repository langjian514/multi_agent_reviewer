# Multi-Agent Code Reviewer

基于 **LangGraph 状态机**编排多个 AI Agent 的智能代码审查系统。通义千问 Qwen 驱动，Docker 一键部署。

## 架构

```
       ┌─────────────┐
       │ Orchestrator │  ← LangGraph 状态机调度
       └──────┬──────┘
              │
    ┌─────────▼─────────┐
    │    Analyzer       │  代码结构分析 + Qwen 深度分析
    │   (复杂度/依赖)    │
    └─────────┬─────────┘
              │
    ┌─────────▼─────────┐
    │    Security       │  安全漏洞扫描 + Qwen 增强检测
    │  (SQL注入/XSS/密钥) │
    └─────────┬─────────┘
              │
    ┌─────────▼─────────┐
    │     Linter        │  编码规范检查 + Qwen 最佳实践
    │   (风格/命名/异常)  │
    └─────────┬─────────┘
              │
    ┌─────────▼─────────┐
    │    Reviewer       │  汇总报告 + Qwen 生成审查摘要
    │   (质量评分/建议)   │
    └─────────┬─────────┘
              │
    ┌─────────▼─────────┐
    │   Reflection      │  自反思决策
    │  (质量达标？重试？)  │
    └─────────┬─────────┘
              │
       ┌──────┴──────┐
       ▼              ▼
    Finalize        Retry → Orchestrator
```

五个 Agent 串行执行，自反思节点根据质量评分决定是否重试（最多 3 次），评分不足时自动降级。

## 特性

- **状态机编排** — LangGraph 管理节点间条件分支、循环和状态传递
- **多 Agent 协作** — Analyzer → Security → Linter → Reviewer → Reflection 分工明确
- **LLM 增强** — 每个 Agent 在规则分析基础上调用 Qwen 做深度分析，结果合并去重
- **自反思重试** — Reflection 节点评估输出质量，评分不达标自动重新审查
- **降级容错** — Agent 超时或 LLM 调用失败时走规则兜底，不影响整体流程
- **全链路追踪** — 记录每个 Agent 耗时、Token 消耗，前端实时展示
- **记忆管理** — 短期滑动窗口 + Milvus 向量存储的长期记忆
- **WebSocket 推送** — 后端实时推送审查状态到前端
- **Docker 部署** — 一条命令启动所有服务

## 技术栈

| 组件 | 选型 |
|---|---|
| 编排框架 | LangGraph (StateGraph) |
| LLM | 通义千问 Qwen (OpenAI 兼容 SDK) |
| 后端 | FastAPI + Uvicorn + WebSocket |
| 前端 | Streamlit |
| 向量数据库 | Milvus v2.4.0 |
| 记忆存储 | Milvus (长期) + 滑动窗口 (短期) |
| 容器化 | Docker Compose |

## 快速开始

### 前置条件

- Docker & Docker Compose
- 通义千问 API Key

### 1. 配置环境变量

```bash
cp .env.example .env
```

编辑 `.env`，填入你的 Qwen API Key：

```ini
QWEN_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
QWEN_MODEL=qwen-plus
```

### 2. 启动服务

```bash
docker compose up -d
```

启动三个容器：

| 服务 | 端口 | 说明 |
|---|---|---|
| Milvus | 19530 | 向量数据库 |
| backend | 8000 | FastAPI 审查 API |
| frontend | 8501 | Streamlit 交互界面 |

### 3. 使用

浏览器打开 `http://localhost:8501`，粘贴代码，点击"开始审查"。

或直接调用 API：

```bash
curl -X POST http://localhost:8000/api/review \
  -H "Content-Type: application/json" \
  -d '{"code": "print(hello world)", "language": "python"}'
```

返回 task_id，轮询获取结果：

```bash
curl http://localhost:8000/api/review/{task_id}
curl http://localhost:8000/api/review/{task_id}/report
```

## API

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/review` | 提交代码审查 |
| GET | `/api/review/{task_id}` | 查询审查状态 |
| GET | `/api/review/{task_id}/report` | 获取审查报告 |
| GET | `/api/agents` | 列出所有 Agent |
| GET | `/api/tools` | 列出可用工具 |
| GET | `/api/metrics` | 系统指标 |
| WS | `/ws/{client_id}` | WebSocket 实时推送 |

## 项目结构

```
├── agents/              # Agent 实现
│   ├── base.py          #   Agent 基类 + Qwen 客户端
│   ├── analyzer.py      #   代码分析 Agent
│   ├── security.py      #   安全扫描 Agent
│   ├── linter.py        #   规范检查 Agent
│   └── reviewer.py      #   报告汇总 Agent
├── api/                 # FastAPI 后端
│   └── main.py          #   REST + WebSocket 端点
├── config/              # 配置管理
│   └── settings.py      #   Qwen、Milvus、超时等配置
├── core/                # 核心编排
│   ├── orchestrator.py  #   LangGraph 状态机
│   └── state.py         #   共享状态定义
├── frontend/            # Streamlit 前端
│   └── streamlit_app.py
├── memory/              # 记忆管理
│   └── manager.py       #   短期 + 长期记忆
├── tools/               # MCP 工具
│   └── mcp.py           #   工具定义与注册
├── utils/               # 工具函数
│   ├── trace.py         #   全链路追踪
│   └── fallback.py      #   降级容错
├── docker-compose.yml   # Docker 编排
├── Dockerfile           # 后端镜像
└── Dockerfile.frontend  # 前端镜像
```

## 配置

核心配置项（通过 `.env` 或环境变量覆盖）：

| 变量 | 默认值 | 说明 |
|---|---|---|
| `QWEN_API_KEY` | — | 通义千问 API Key |
| `QWEN_MODEL` | `qwen-plus` | LLM 模型名 |
| `QWEN_BASE_URL` | `https://dashscope.aliyuncs.com/compatible-mode/v1` | API 端点 |
| `MILVUS_HOST` | `localhost` | Milvus 地址 |
| `MILVUS_PORT` | `19530` | Milvus 端口 |
| `max_retries` | `3` | 自反思最大重试次数 |
| `min_quality_score` | `0.7` | 质量评分阈值 |
| `total_timeout` | `300` | 审查任务总超时（秒） |

## 本地开发（无 Docker）

```bash
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt

# 确保 Milvus 已运行，然后启动后端
uvicorn api.main:app --reload --port 8000

# 新终端，启动前端
streamlit run frontend/streamlit_app.py
```
