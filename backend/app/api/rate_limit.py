"""Límite de peticiones en memoria (ventana deslizante por IP y ruta), sin dependencias.

Suficiente para una sola instancia (Render gratuito). Con varias instancias haría falta un
almacén compartido (ADR 0004). La IP sale de `client_ip()`, que no confía en X-Forwarded-For
salvo detrás de un proxy declarado (`TRUSTED_PROXY_HOPS`).
"""

import math
import threading
import time
from collections import deque

from fastapi import HTTPException, Request, status

from backend.app.api.client_ip import client_ip

_MAX_KEYS = 1_000


class RateLimiter:
    def __init__(self) -> None:
        self._hits: dict[tuple[str, str], deque[float]] = {}
        self._lock = threading.Lock()

    def hit(self, key: tuple[str, str], limit: int, window: float) -> float | None:
        """Registra una petición; devuelve los segundos a esperar si se excedió el límite."""
        now = time.monotonic()
        with self._lock:
            if len(self._hits) > _MAX_KEYS:
                self._prune(now, window)
            hits = self._hits.setdefault(key, deque())
            while hits and now - hits[0] >= window:
                hits.popleft()
            if len(hits) >= limit:
                return window - (now - hits[0])
            hits.append(now)
            return None

    def _prune(self, now: float, window: float) -> None:
        for key in [k for k, v in self._hits.items() if not v or now - v[-1] >= window]:
            del self._hits[key]

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


limiter = RateLimiter()


def rate_limit(name: str, limit: int, window_seconds: int):
    """Dependencia de FastAPI: `dependencies=[Depends(rate_limit("auth_token", 10, 60))]`."""

    def dependency(request: Request) -> None:
        ip = client_ip(request) or "desconocida"
        retry_after = limiter.hit((name, ip), limit, window_seconds)
        if retry_after is not None:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Demasiadas solicitudes. Intenta de nuevo en unos momentos.",
                headers={"Retry-After": str(max(1, math.ceil(retry_after)))},
            )

    return dependency
