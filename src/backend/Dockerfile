FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
RUN useradd --create-home --uid 10001 chargeopt
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY alembic.ini docker-entrypoint.sh ./
COPY alembic ./alembic
COPY app ./app
USER chargeopt
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=4s --start-period=40s --retries=6 \
  CMD python -c "import sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health/ready', timeout=3).status == 200 else 1)"
ENTRYPOINT ["sh", "/app/docker-entrypoint.sh"]

FROM runtime AS test
USER root
COPY requirements-dev.txt .
RUN pip install -r requirements-dev.txt
COPY tests ./tests
USER chargeopt
ENTRYPOINT []
CMD ["pytest", "-q"]
