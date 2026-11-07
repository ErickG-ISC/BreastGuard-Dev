# Migración de hosting (solo si el modelo deja de caber en Render)

**Hoy no hace falta.** Con LiteRT, el peor caso medido es 419 MB de 512 (ADR 0013). Esta guía es
para el día en que un modelo nuevo no quepa: más de unos 400 MB de pico en
`ml_tools/measure_memory.py`, dentro de Docker con `--memory=512m`.

**No se cambia de proveedor sin aprobación.**

## Antes de migrar, en este orden
1. **`MAX_STUDIES_IN_FLIGHT=1`** en Render: el peor caso pasa a ser el de un estudio.
2. **Cuantizar el modelo al exportarlo** (`TFLiteConverter` con `optimizations=[DEFAULT]`, pesos en int8).
   - Suele bajar el modelo a una cuarta parte.
   - Hay que repetir la paridad (`ml_tools/parity.py`) y aceptar una tolerancia mayor, documentada.
3. **ONNX Runtime**, solo si el modelo trae operaciones que LiteRT no soporta. Requiere su propia medición y su propia prueba de paridad.

## Alternativas
Precios de referencia; verifícalos antes de decidir.

| Opción | RAM | Costo aproximado | Ventajas | Desventajas |
|---|---|---|---|---|
| **Render Starter** | 512 MB | ~7 USD/mes | No se duerme; mismo despliegue | **Misma RAM**: no resuelve la memoria |
| **Render Standard** | 2 GB | ~25 USD/mes | Cero cambios de código ni de configuración | Costo mensual sin crédito |
| **Azure App Service B1** (Linux, Azure for Students) | 1.75 GB | ~13 USD/mes, pagados del crédito de 100 USD | Sin tarjeta; no se duerme; alcanza para el semestre | Otra consola y otro despliegue; el crédito se acaba |
| **Servicio de inferencia aparte** (contenedor con LiteRT) | El que tenga ese servicio | Depende del proveedor | El backend sigue en Render gratuito | Las imágenes salen del backend: otro secreto, otra superficie de ataque, latencia y dos despliegues |

**Recomendación**, si llega el caso: **Azure App Service B1** con el crédito de estudiante. Es la
única opción que da más RAM sin costo directo y sin partir la arquitectura.

## Guía: Render → Azure App Service (Linux, Python 3.12)
1. **Crear el recurso.** Portal de Azure → App Service → Web App:
   - Runtime: Python 3.12, Linux.
   - Plan: B1, en la región más cercana a Supabase (us-east).
2. **Variables** (Configuration → Application settings): las mismas de Render (ver
   `docs/despliegue.md`). En particular:
   - `DATABASE_URL`: el Transaction pooler sin contraseña;
   - `APP_DB_PASSWORD`, `SECRET_KEY`, `SUPABASE_URL`, `SUPABASE_KEY`, `SUPABASE_BUCKET`;
   - `MODEL_BUCKET`, `MODEL_PREFIX`, `FRONTEND_ORIGIN`, `PUBLIC_APP_URL`;
   - `REMINDER_CRON_SECRET`, `EMAIL_*`.

   Nunca pegues los valores en el repo.
3. **Comando de inicio** (Configuration → General settings):
   `uvicorn backend.app.main:app --host 0.0.0.0 --port 8000`. Azure ejecuta desde la raíz del repo, que es lo que la app necesita.
4. **Proxy:** Azure pone un frontal delante de la app, así que `TRUSTED_PROXY_HOPS=1`. Verifica la IP en `GET /api/v1/audit` como se explica en `docs/despliegue.md`, sección 1.
5. **Health check:** Monitoring → Health check, ruta `/api/v1/health`.
6. **Despliegue:** Deployment Center → GitHub, rama `main`. Sigue la regla de siempre: **migrar desde tu computadora antes de desplegar**, nunca en el build.
7. **Frontend:** en Vercel, `VITE_API_URL=https://<app>.azurewebsites.net/api/v1`. Vuelve a desplegar.
8. **CORS:** `FRONTEND_ORIGIN` con el dominio de Vercel.
9. **Cron:** en GitHub Actions, cambia la variable `API_URL` a la URL de Azure.
10. **Verificación:** el smoke test de solo lectura contra la URL nueva y **Metrics → Memory working set** tras un DICOM.
11. **Vuelta atrás:** Render sigue configurado. Basta regresar `VITE_API_URL` y `API_URL`.
