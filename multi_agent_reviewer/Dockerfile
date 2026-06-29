# ============================================================
# Backend — FastAPI + Qwen + Milvus
# ============================================================
FROM python:3.13-slim

LABEL maintainer="multi-agent-reviewer"
LABEL description="Multi-Agent Code Reviewer Backend"

WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 复制依赖清单
COPY requirements.txt .

# 安装 Python 依赖（新版本 grpcio 有预制 wheel，无需编译）
RUN pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt

# 复制项目代码
COPY . .

# 创建数据目录
RUN mkdir -p /app/data/traces

EXPOSE 8000

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000", "--log-level", "info"]
