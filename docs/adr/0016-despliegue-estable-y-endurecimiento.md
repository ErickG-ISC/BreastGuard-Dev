# ADR 0016 — Despliegue estable y endurecimiento

- Estado: aceptado (Semana 5, 2026-11-07)

## Contexto
Antes de la demo el backend desplegado tiene que ser estable con el modelo cargado (ADR 0013), y
el despliegue no puede quedar a medias: código nuevo contra una base sin migrar. También hacía
falta revisar secretos, dependencias, cabeceras y logs.

## Decisión

### Health y orden "migrar antes de desplegar"
- `GET /api/v1/health` devuelve:
  - `version`: el commit, de `RENDER_GIT_COMMIT[:7]`, o `dev`;
  - `migration`: `ok`, `ahead` o `behind`;
  - `schema_revision` y `code_revision`;
  - `model` y `model_version`.

  Nunca devuelve el host, el usuario ni el detalle de un error; esos van al log, solo como tipo.
- **Migración 0019:** `GRANT SELECT ON public.alembic_version` a `app_user` (solo lectura). La Data API sigue sin acceso.
- **Base atrasada:** si la base está **atrasada** respecto del código (o la revisión no se puede leer), `/health` responde **503**. Render usa `/api/v1/health` como health check: un despliegue sin migrar no pasa y queda el anterior.
- **Base adelantada:** `ahead` (base más nueva que el código) responde 200. Es justo lo que ocurre al migrar antes de desplegar.
- **Procedimiento:** está en `docs/despliegue.md`:
  1. migrar desde la computadora;
  2. hacer push a `main`;
  3. Render despliega;
  4. correr el smoke test.

### Cabeceras
- **API**, en todas las respuestas `/api/…`:
  - `Cache-Control: no-store` (ya existía);
  - `X-Content-Type-Options: nosniff`;
  - `Referrer-Policy: no-referrer`;
  - `X-Frame-Options: DENY`;
  - `Content-Security-Policy: default-src 'none'; frame-ancestors 'none'`;
  - HSTS.
- **Documentación de la API:** `/docs`, `/redoc` y `/openapi.json` solo existen con `BREASTGUARD_ENV=development`.
- **Vercel (`frontend/vercel.json`):**
  - CSP: `script-src 'self'`, sin inline ni eval (el build no tiene scripts inline). `style-src 'self' 'unsafe-inline'`, que Emotion/MUI necesita. `img-src` permite `data:` (QR), `blob:` (vista previa) y `https://*.supabase.co` (URLs firmadas). `connect-src` permite `https://*.onrender.com` y `https://*.supabase.co`. Además `frame-ancestors 'none'`, `object-src 'none'` y `upgrade-insecure-requests`;
  - `Permissions-Policy` sin cámara, micrófono, geolocalización, pagos ni USB;
  - `Cross-Origin-Opener-Policy: same-origin`;
  - lo que ya había: nosniff, Referrer-Policy y X-Frame-Options.
- **Dominios con comodín:** así no se escriben en el repo los ids del proyecto. Si se cambia de proveedor (`docs/migracion-hosting.md`), hay que actualizar `connect-src`.
- **Verificación:** el build servido con esa CSP en Chromium no muestra violaciones. La página, el service worker y el manifest cargan; la única violación fue la API local del build de desarrollo.
- **CORS:** expone solo `Content-Disposition`, para el nombre del archivo exportado.

### Secretos
- `gitleaks` 8.28 sobre **todo el historial** (191 commits): sin fugas.
- Grep de patrones del proyecto en todas las líneas agregadas: JWT, llaves de Supabase y Resend, `postgresql://usuario:contraseña@`, `SECRET_KEY=` y `APP_DB_PASSWORD=`. Solo dio marcadores y ejemplos (`.env.example`, URLs RDS de ejemplo del prototipo, credenciales efímeras de CI). **No hay que rotar nada por el historial.**
- Nunca se commiteó un `.env`, `.pem`, `.key` ni `.dump`.

### Dependencias
- **Python:** `pip-audit` (fijado en `requirements-dev.txt`).
  - Producción: dos avisos aceptados, sin parche disponible. Justificación en `docs/limitaciones-conocidas.md`.
  - Desarrollo: `pypdf` subió a 6.21.4, que corrige 4 CVE.
- **npm:** `npm audit fix`, sin cambios de versión mayor, corrigió las 3 altas (vite, follow-redirects y source-map-js). Quedan 2 bajas y 4 moderadas, todas del build de la PWA (`vite-plugin-pwa` → `workbox-build`). No llegan al navegador.
- **CI:** las acciones de GitHub están fijadas a SHA. El workflow `audit.yml` corre en cada push y cada lunes y no bloquea la fusión. Falla solo ante vulnerabilidades nuevas (altas o críticas en npm).

### Logs
- `tests/api/test_logs_sin_datos.py` captura **todos** los loggers en DEBUG durante el recorrido completo:
  - registro, inicio de sesión y un intento fallido;
  - diario con nota;
  - compartir e importar (con un código inválido);
  - nota y revisión de la médica;
  - PDF, HL7 y un fallo de Storage.
- Verifica que no aparezcan notas, la recomendación, el código del paquete, los JWT, la contraseña, los correos sin enmascarar ni el nombre.
- Tiene una guarda contra un falso verde: debe aparecer el registro del correo (enmascarado).
- Revisión manual de cada `logger.*` con argumentos: solo ids, versiones, orígenes de CORS y correos enmascarados.

### Smoke test y arranque en frío
- `backend/scripts/smoke_deployed.py --api … --web …` es de solo lectura y no usa login: solo GET y un preflight OPTIONS (probado). Comprueba health, endpoints públicos, el 401 sin token, la documentación oculta, las cabeceras, CORS, la reescritura de la SPA y que `sw.js` no se cachee.
- Render gratuito se duerme tras unos 15 minutos sin tráfico y da 750 horas al mes, suficientes para un servicio 24/7.
  - El repositorio es **público**, así que los minutos de Actions no tienen límite. El cron de `reminders.yml` sigue en `*/15` y de paso lo mantiene despierto.
  - GitHub puede retrasar el cron, así que **antes de la demo se despierta a mano** (`docs/demo.md`).

## Consecuencias
- Un push sin migrar antes deja el servicio en la versión anterior (Render marca el despliegue como fallido). Es lo buscado.
- La CSP con comodines permite cualquier subdominio de `onrender.com` o `supabase.co`. Fijar los hosts exactos es más estricto, pero obliga a cambiar `vercel.json` con cada proyecto.
- Respaldo antes de la demo: lo corre la persona dueña de la credencial (`docs/demo.md`). Contiene hashes y no va al repositorio.
