FROM python:3.11-slim

WORKDIR /app

COPY . /app

RUN pip install --no-cache-dir -U pip \
    && pip install --no-cache-dir ./backend

ENV PYTHONPATH=/app/backend/src
ENV FLOW_AGENT_CONFIG_FILE=/app/config/prod.toml

EXPOSE 8787 8788

CMD ["python", "-m", "flow_agent.main"]
