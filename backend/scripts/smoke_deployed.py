"""Smoke test del entorno DESPLEGADO, de SOLO LECTURA y sin iniciar sesión (ADR 0016).

No crea, modifica ni borra nada; no usa credenciales; solo hace GET y un preflight OPTIONS.
Úsalo después de cada despliegue y antes de la demo:

    python -m backend.scripts.smoke_deployed --api https://<api>.onrender.com \\
        --web https://<app>.vercel.app

Comprueba:
- /health: 200, migración `ok` o `ahead`, modelo cargado (versión y commit);
- endpoints públicos (consentimiento, planes, blog, guía, ficha del modelo) responden 200;
- lo protegido responde 401 sin token, y la documentación de la API no es pública;
- cabeceras de seguridad de la API y del frontend (CSP, nosniff, Referrer-Policy, no-store);
- CORS: el origen del frontend está permitido y uno ajeno no;
- el frontend reescribe rutas profundas a la SPA y no cachea el service worker.

Render gratuito se duerme: la primera petición puede tardar ~1 minuto (se reintenta).
"""

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass

TIMEOUT = 90
FOREIGN_ORIGIN = "https://origen-ajeno.example"


@dataclass
class Result:
    status: int
    headers: dict[str, str]
    body: bytes

    def json(self):
        return json.loads(self.body.decode("utf-8"))


Fetch = Callable[[str, str, dict[str, str]], Result]


def http_fetch(method: str, url: str, headers: dict[str, str]) -> Result:
    request = urllib.request.Request(url, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:  # noqa: S310
            return Result(
                response.status,
                {k.lower(): v for k, v in response.headers.items()},
                response.read(),
            )
    except urllib.error.HTTPError as exc:
        return Result(exc.code, {k.lower(): v for k, v in exc.headers.items()}, exc.read())


PUBLIC = ["/consent/current", "/plans", "/blog", "/blog/faq", "/self-exam/guide", "/model/card"]
PROTECTED = [
    "/auth/me",
    "/analyses",
    "/symptoms",
    "/doctor/patients/summary",
    "/admin/tenants",
    "/audit",
]
HIDDEN = ["/docs", "/openapi.json", "/redoc"]


def run(api: str, web: str | None, fetch: Fetch = http_fetch) -> list[tuple[bool, str]]:
    api = api.rstrip("/")
    base = f"{api}/api/v1"
    checks: list[tuple[bool, str]] = []

    def check(ok: bool, text: str) -> None:
        checks.append((bool(ok), text))

    # 1. Health (con reintentos: el plan gratuito puede estar dormido)
    health = None
    for attempt in range(3):
        try:
            health = fetch("GET", f"{base}/health", {})
            break
        except OSError:
            time.sleep(5 * (attempt + 1))
    if health is None:
        check(False, "health: sin respuesta")
        return checks
    body = health.json() if health.body else {}
    check(health.status == 200, f"health 200 (fue {health.status})")
    check(body.get("migration") in ("ok", "ahead"), f"migración {body.get('migration')}")
    check(
        body.get("model") == "loaded", f"modelo {body.get('model')} {body.get('model_version', '')}"
    )
    check(
        "postgres" not in health.body.decode("utf-8", "replace").lower(),
        "health sin datos de conexión",
    )
    checks.append((True, f"versión desplegada {body.get('version')}"))

    # 2. Públicos, protegidos y documentación oculta
    for path in PUBLIC:
        check(fetch("GET", f"{base}{path}", {}).status == 200, f"público {path} 200")
    for path in PROTECTED:
        status = fetch("GET", f"{base}{path}", {}).status
        check(status == 401, f"protegido {path} 401 sin token (fue {status})")
    for path in HIDDEN:
        status = fetch("GET", f"{api}{path}", {}).status
        check(status == 404, f"{path} no público (fue {status})")

    # 3. Cabeceras de seguridad de la API
    plans = fetch("GET", f"{base}/plans", {})
    check(plans.headers.get("x-content-type-options") == "nosniff", "API nosniff")
    check(plans.headers.get("cache-control") == "no-store", "API no-store")
    check("default-src 'none'" in plans.headers.get("content-security-policy", ""), "API CSP")

    # 4. CORS
    if web:
        web = web.rstrip("/")
        preflight = {"Origin": web, "Access-Control-Request-Method": "GET"}
        allowed = fetch("OPTIONS", f"{base}/plans", preflight)
        check(
            allowed.headers.get("access-control-allow-origin") == web,
            "CORS permite el frontend",
        )
        foreign = fetch("GET", f"{base}/plans", {"Origin": FOREIGN_ORIGIN})
        check("access-control-allow-origin" not in foreign.headers, "CORS rechaza otro origen")

        # 5. Frontend
        home = fetch("GET", f"{web}/", {})
        check(home.status == 200, "frontend 200")
        csp = home.headers.get("content-security-policy", "")
        check("frame-ancestors 'none'" in csp and "script-src 'self'" in csp, "frontend CSP")
        check(home.headers.get("x-content-type-options") == "nosniff", "frontend nosniff")
        check(home.headers.get("referrer-policy") == "no-referrer", "frontend Referrer-Policy")
        deep = fetch("GET", f"{web}/medico/pacientes/00000000-0000-0000-0000-000000000000", {})
        check(deep.status == 200 and b'id="root"' in deep.body, "reescritura SPA")
        sw = fetch("GET", f"{web}/sw.js", {})
        check(sw.headers.get("cache-control", "").startswith("no-cache"), "sw.js sin caché")
    return checks


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--api", required=True, help="URL del backend, sin /api/v1")
    parser.add_argument("--web", help="URL del frontend (Vercel)")
    args = parser.parse_args()
    checks = run(args.api, args.web)
    for ok, text in checks:
        print(f"[{'OK ' if ok else 'FALLA'}] {text}")
    failed = sum(not ok for ok, _ in checks)
    print(f"\n{len(checks) - failed} correctas, {failed} fallidas")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
