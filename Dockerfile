FROM python:3.12-slim

LABEL org.opencontainers.image.title="Pplanner" \
      org.opencontainers.image.description="Private single-user notes, projects and Gantt planner" \
      org.opencontainers.image.licenses="MIT"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PPLANNER_DB=/data/planner.sqlite3 \
    PPLANNER_TIMEZONE=Europe/Rome

RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 pplanner \
    && useradd --uid 10001 --gid pplanner --no-create-home --shell /usr/sbin/nologin pplanner \
    && mkdir /data \
    && chown pplanner:pplanner /data

WORKDIR /app
COPY server.py project_store.py backup_store.py ./
COPY static/ ./static/
COPY imgs/ ./imgs/
COPY LICENSE ./

USER 10001:10001
VOLUME ["/data"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/clock', timeout=3).read()"

CMD ["python", "server.py", "--host", "0.0.0.0", "--port", "8000"]
