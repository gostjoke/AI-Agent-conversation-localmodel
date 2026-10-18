# Backend: FastAPI + agent. 後端：FastAPI + agent
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    AGENT_WORKSPACE=/data/workspace HF_HOME=/data/hf
WORKDIR /app

COPY requirements*.txt ./
RUN pip install --no-cache-dir -r requirements.txt
# Optional reranker (adds torch, large) 選用重排序（含 torch，映像較大）: --build-arg WITH_RERANK=1
ARG WITH_RERANK=0
RUN if [ "$WITH_RERANK" = "1" ]; then pip install --no-cache-dir -r requirements-rerank.txt; fi

COPY . .
RUN useradd -m -u 1000 agent && mkdir -p /data/workspace /data/hf && chown -R agent /data
USER agent

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/health')"
# 0.0.0.0 inside container only; not published to host (Nginx in front). 只在容器網路內開放，由 Nginx 對外
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
