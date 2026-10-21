# ADR 0004 — Auditoría de accesos y límite de peticiones

- Estado: aceptado (Semana 1, 2026-10-21)

## Decisión
- **Auditoría (CU-13)** en `clinical.audit_log`, con RLS por tenant y de solo inserción para la app.
  - Se escribe en la misma transacción que la acción. Se registran `image.upload`, `image.list`, `image.read`, `image.denied` (404 de una imagen ajena o inexistente, en el tenant de quien preguntó), `audit.read` y las altas y cambios de la administración.
  - Guarda quién, rol, acción, recurso, cuándo e IP. Nunca datos clínicos, rutas de Storage ni tokens.
  - `image.read` registra la **emisión** de la URL firmada (válida 300 s), no la descarga.
- **IP del cliente**: por defecto la de la conexión TCP; `X-Forwarded-For` se ignora. Detrás de un proxy de confianza (Render), `TRUSTED_PROXY_HOPS=1` toma la entrada que agregó ese proxy, contando desde la derecha, nunca las que manda el cliente.
- **Límite de peticiones** en memoria, por IP y ruta: `/auth/token` 10/min, `/auth/register` 5/min, `/images/upload` 20/min.

## Consecuencias
- El límite vale para una sola instancia (Render gratuito). Con varias instancias o workers haría falta un almacén compartido (por ejemplo Redis).
- Un atacante con muchas IP puede repartir intentos. Es un riesgo aceptado para el prototipo; bcrypt hace caro cada intento.
- Si `TRUSTED_PROXY_HOPS` no coincide con la infraestructura real, la IP auditada será la del proxy o una falsificable. Se configura junto con el despliegue.
