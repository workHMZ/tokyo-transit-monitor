# syntax=docker/dockerfile:1.7
FROM python:3.13-slim

ENV DEBIAN_FRONTEND=noninteractive

# 只安装必要的依赖（不再需要 Chrome）
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        ca-certificates \
        fonts-noto-cjk; \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 先装依赖
COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-cache-dir -r requirements.txt

# 再拷贝源码
COPY . .

# 启动命令
CMD ["python", "app.py"]