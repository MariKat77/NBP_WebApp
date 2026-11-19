"""Prosta aplikacja webowa prezentująca kurs USD ze strony NBP"""
from __future__ import annotations

import json
import logging
import os
import sys
from typing import Optional

from flask import Flask, jsonify, render_template

from nbp_client import NBPClient, NBPError


class JsonFormatter(logging.Formatter):
    """Logi JSON na stdout Cloud Logging mapuje pole `severity` automatycznie na poziom logowania w konsoli GCP"""

    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "severity": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
        }
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False)


def configure_logging() -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(os.getenv("LOG_LEVEL", "INFO").upper())


def create_app(client: Optional[NBPClient] = None) -> Flask:
    app = Flask(__name__)
    client = client or NBPClient(
        base_url=os.getenv("NBP_API_URL", "https://api.nbp.pl/api"),
        code=os.getenv("CURRENCY_CODE", "USD"),
        timeout=float(os.getenv("NBP_TIMEOUT_SECONDS", "5")),
        cache_ttl=int(os.getenv("CACHE_TTL_SECONDS", "900")),
    )

    @app.get("/")
    def index():
        try:
            result = client.get_rate()
        except NBPError:
            app.logger.exception("Błąd NBP")
            return (
                render_template(
                    "index.html",
                    error="Dane NBP są chwilowo niedostępne. Spróbuj za chwilę.",
                ),
                503,
            )
        return render_template("index.html", rate=result.rate, stale=result.stale)

    @app.get("/api/rate")
    def api_rate():
        try:
            result = client.get_rate()
        except NBPError:
            return jsonify(error="NBP unavailable"), 503
        r = result.rate
        return jsonify(
            currency=r.currency,
            code=r.code,
            mid=r.mid,
            effectiveDate=r.effective_date,
            table=r.table_no,
            stale=result.stale,
        )

    @app.get("/healthz")
    def healthz():
        # Liveness/readiness NIE zależą od NBP awaria NBP nie powinna powodować restartu kontenera
        return jsonify(status="ok")

    return app


configure_logging()
app = create_app() if os.getenv("SKIP_APP_INIT") != "1" else None
