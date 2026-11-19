"""Klient NBP Web API"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)


class NBPError(Exception):
    """Błąd pobierania lub parsowania danych z NBP."""


@dataclass(frozen=True)
class Rate:
    currency: str
    code: str
    mid: float
    effective_date: str
    table_no: str


@dataclass(frozen=True)
class RateResult:
    rate: Rate
    stale: bool  # Prawda, jeśli dane pochodzą z cache'u (NBP niedostępne)
    fetched_at: float


class NBPClient:
    def __init__(
        self,
        base_url: str = "https://api.nbp.pl/api",
        code: str = "USD",
        timeout: float = 5.0,
        cache_ttl: int = 900,
        session: Optional[requests.Session] = None,
    ) -> None:
        self._url = f"{base_url.rstrip('/')}/exchangerates/rates/a/{code.lower()}/"
        self._code = code.upper()
        self._timeout = timeout
        self._ttl = cache_ttl
        self._session = session or self._build_session()
        self._lock = threading.Lock()
        self._cached: Optional[RateResult] = None

    @staticmethod
    def _build_session() -> requests.Session:
        retry = Retry(
            total=3,
            backoff_factor=0.5,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=("GET",),
        )
        session = requests.Session()
        session.mount("https://", HTTPAdapter(max_retries=retry))
        session.headers["Accept"] = "application/json"
        return session

    def _fetch(self) -> Rate:
        try:
            resp = self._session.get(
                self._url, params={"format": "json"}, timeout=self._timeout
            )
            resp.raise_for_status()
            payload = resp.json()
            entry = payload["rates"][0]
            return Rate(
                currency=payload["currency"],
                code=payload["code"],
                mid=float(entry["mid"]),
                effective_date=entry["effectiveDate"],
                table_no=entry["no"],
            )
        except (requests.RequestException, ValueError, KeyError, IndexError, TypeError) as exc:
            raise NBPError(f"Nie udało się pobrać kursu {self._code} z NBP: {exc}") from exc
        
    #Zwraca kurs z cache'u lub pobiera go z NBP, jeśli cache jest nieaktualny lub pusty
    def get_rate(self) -> RateResult:
        with self._lock:
            now = time.time()
            cached = self._cached
            if cached and now - cached.fetched_at < self._ttl:
                return cached
            try:
                rate = self._fetch()
            except NBPError:
                if cached:
                    logger.warning("NBP niedostępne - dane z cache'u", exc_info=True)
                    return RateResult(cached.rate, True, cached.fetched_at)
                raise
            self._cached = RateResult(rate, False, now)
            logger.info("Pobrano kurs %s=%s (%s)", rate.code, rate.mid, rate.effective_date)
            return self._cached
