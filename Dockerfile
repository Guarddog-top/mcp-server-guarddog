# Smithery 构建镜像：Node 启动器 + Python 3.11 引擎预装
# （bin/guarddog-mcp.js 首次运行检测到 ~/.guarddog-mcp/venv 已存在即秒起）
FROM node:20-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
      python3 python3-venv python3-pip ca-certificates curl \
    && rm -rf /var/lib/apt/lists/* \
    && python3 --version | grep -q '3.1[0-9]'

WORKDIR /app

# 预装 Python 引擎依赖（镜像内建 venv，运行时零等待）
RUN python3 -m venv /root/.guarddog-mcp/venv \
    && /root/.guarddog-mcp/venv/bin/pip install --no-cache-dir --quiet \
       "mcp>=2.3" httpx redis asyncpg pydantic-settings

COPY package.json ./
COPY bin ./bin
COPY lib ./lib

ENV HOME=/root
CMD ["node", "bin/guarddog-mcp.js"]
