# Despliegue de prueba (Render + Vercel)

El backend va en **Render** (plan gratuito, unos 512 MB) y el frontend en **Vercel**. La base de datos y Storage están en **Supabase**. Nada de esto requiere commitear secretos.

## 0. Antes de desplegar (una vez, desde tu computadora)
1. Migra la base, siempre a mano y nunca en el build de Render: `alembic -c backend/alembic.ini upgrade head`.
2. Revisa en Supabase que tanto `medical_images` como `ml-models` sean buckets **privados**. Para el primero puedes usar `python -m backend.scripts.check_storage`.
3. Si el modelo aún no está en el bucket, súbelo: `python -m backend.ml_tools.upload_model --model-dir <carpeta>`.

## 1. Backend en Render
1. En Render: **New → Blueprint** y elige el repo. Render lee `render.yaml`.
2. Carga los valores marcados `sync: false`:
   | Variable | Valor |
   |---|---|
   | `DATABASE_URL` | La cadena del **Transaction pooler** (puerto 6543) **sin la contraseña**: `postgresql://postgres.<ref>@aws-0-us-east-1.pooler.supabase.com:6543/postgres`. La app solo usa host, base y sufijo `.<ref>`, y se conecta como `app_user`. |
   | `APP_DB_PASSWORD` | La misma que usaste al migrar. |
   | `SUPABASE_URL` / `SUPABASE_KEY` | Project Settings → API (llave `service_role`, solo en el backend). |
   | `FRONTEND_ORIGIN` | `https://<tu-app>.vercel.app` (con `https://`). |
3. Despliega. El primer arranque descarga el modelo (unos 16 MB) del bucket privado.
4. Verifica: `https://<tu-api>.onrender.com/api/v1/health` debe responder `{"status":"ok","database":"connected","model":"loaded"}`.
5. Mide la RAM: en Render → **Metrics → Memory**, después de un análisis. En Docker con 512 MB se midió un pico de 184 MB (ADR 0006).

La app **no arranca** (falla cerrado, es intencional):
- si falta `APP_DB_PASSWORD`, porque nunca usa la contraseña del dueño;
- si el rol con el que se conecta es superusuario, tiene BYPASSRLS o no es `app_user`.

**Pooler:** la app usa el **Transaction pooler** (6543). Es seguro porque el contexto RLS es `set_config(..., true)` por transacción, y el driver (psycopg2) no usa sentencias preparadas del servidor. Las **migraciones** se corren desde tu computadora por el **Session pooler** (5432), con la URL del dueño **con** contraseña de tu `.env` local.

**Verifica la IP real detrás del proxy (`TRUSTED_PROXY_HOPS=1`):**
1. Inicia sesión como paciente en la app desplegada y abre un análisis.
2. Como `tenant_admin`, consulta `GET /api/v1/audit` y compara la `ip` con tu IP pública (por ejemplo, la que muestra https://ifconfig.me).
3. Si aparece una IP de Render o de Cloudflare en lugar de la tuya, ajusta `TRUSTED_PROXY_HOPS` (prueba con `2`) y repite. Sin esto, el límite de peticiones y la auditoría usarían una IP equivocada.

## 2. Frontend en Vercel
1. **Add New → Project** y elige el repo, con **Root Directory** `frontend`. Framework: Vite.
2. Variable de entorno: `VITE_API_URL=https://<tu-api>.onrender.com/api/v1`.
3. Despliega. `vercel.json` reescribe todas las rutas a `index.html`, que es una SPA.
4. Vuelve a Render y confirma que `FRONTEND_ORIGIN` coincide con el dominio de Vercel, con `https://` (los espacios y la `/` final se ignoran). Los *previews* de Vercel tienen otro dominio y quedarán bloqueados por CORS: es lo esperado.

## 3. Primer usuario administrador
Desde tu computadora, con el `.env` apuntando a la misma base:
`python -m backend.scripts.create_platform_admin --email tu@correo.com --name "Tu nombre"`

## Pruebas en CI (GitHub Actions)

`.github/workflows/ci.yml` corre dos jobs en cada push y PR:

- **backend**: levanta un servicio `postgres:17` en el puerto 54329 y define `TEST_DATABASE_URL`. `tests/pgtest.py` crea una base temporal, aplica las migraciones con Alembic y crea el rol de prueba de la app (`bg_app_test`, NOSUPERUSER NOBYPASSRLS), así que las pruebas de RLS corren contra Postgres real, igual que en local con `docker compose up -d db`. `REQUIRE_POSTGRES=1` hace que fallen (en vez de omitirse) si la base no responde. Luego `ruff check`, `ruff format --check` y `pytest -q`.
- **frontend**: `npm ci`, `npm run lint` (oxlint), `npm run build` y `npm run check:sw`, que verifica que el service worker solo precachee archivos estáticos y no guarde respuestas de la API ni imágenes.

## Problemas comunes
- **`model: unavailable` en `/health`:** el bucket o el prefijo están mal, o el modelo no se subió. Revisa los logs de Render; solo registran el tipo de error.
- **Error de CORS en el navegador:** `FRONTEND_ORIGIN` no coincide con el dominio exacto de Vercel.
- **El primer request tarda ~1 min:** el plan gratuito duerme. Despiértalo antes de la demo.
