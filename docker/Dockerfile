FROM python:3.11-slim

WORKDIR /app

ARG HTTP_PROXY
ARG HTTPS_PROXY
ARG NO_PROXY

RUN export http_proxy="$HTTP_PROXY" \
    https_proxy="$HTTPS_PROXY" \
    no_proxy="$NO_PROXY" \
    HTTP_PROXY="$HTTP_PROXY" \
    HTTPS_PROXY="$HTTPS_PROXY" \
    NO_PROXY="$NO_PROXY" \
    && apt-get update \
    && apt-get install -y --no-install-recommends nodejs npm \
    && rm -rf /var/lib/apt/lists/*

# 只复制应用源码和 Python 包描述，配置与运行时数据由 Compose 在运行时挂载。
COPY backend /app/backend

RUN export http_proxy="$HTTP_PROXY" \
    https_proxy="$HTTPS_PROXY" \
    no_proxy="$NO_PROXY" \
    HTTP_PROXY="$HTTP_PROXY" \
    HTTPS_PROXY="$HTTPS_PROXY" \
    NO_PROXY="$NO_PROXY" \
    && pip install --no-cache-dir -U pip \
    && pip install --no-cache-dir ./backend

ENV PYTHONPATH=/app/backend/src

# 当前正式启动入口是 bootstrap.main；HTTP、CLI 和 dashboard 不在默认容器中启用。
CMD ["python", "-m", "bootstrap.main"]
