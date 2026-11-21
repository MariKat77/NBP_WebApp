# syntax=docker/dockerfile:1.7

# builder: instalacja zależności do wirtualnego środowiska
FROM python:3.12-slim AS builder
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /build
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
COPY app/requirements.txt .
RUN pip install -r requirements.txt

# runtime: minimalny obraz, użytkownik nie-root
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    PORT=8080

RUN groupadd --system --gid 10001 app \
 && useradd --system --uid 10001 --gid app --no-create-home app

COPY --from=builder /opt/venv /opt/venv
WORKDIR /srv/app
COPY --chown=app:app app/app.py app/nbp_client.py ./
COPY --chown=app:app app/templates ./templates

USER 10001
EXPOSE 8080

# Cloud Logging zbiera stdout/stderr kontenera
CMD ["sh", "-c", "exec gunicorn --bind 0.0.0.0:${PORT} --workers 2 --threads 4 --access-logfile - --error-logfile - app:app"]
