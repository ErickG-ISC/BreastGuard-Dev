"""IP del cliente para auditoría y límite de peticiones.

Por defecto se usa la IP de la conexión TCP y se ignora `X-Forwarded-For`, que el cliente puede
falsificar. Detrás de un proxy de confianza (Render), `TRUSTED_PROXY_HOPS=1` toma la entrada que
agregó ese proxy: la N-ésima desde la DERECHA, nunca las de la izquierda, que vienen del cliente.
"""

import ipaddress
import os

from fastapi import Request


def trusted_proxy_hops() -> int:
    try:
        return max(0, int(os.environ.get("TRUSTED_PROXY_HOPS", "0")))
    except ValueError:
        return 0


def client_ip(request: Request) -> str | None:
    hops = trusted_proxy_hops()
    if hops:
        forwarded = request.headers.get("x-forwarded-for", "")
        entries = [part.strip() for part in forwarded.split(",") if part.strip()]
        if len(entries) >= hops:
            candidate = entries[-hops]
            try:
                return str(ipaddress.ip_address(candidate))
            except ValueError:
                return None
    return request.client.host if request.client else None
