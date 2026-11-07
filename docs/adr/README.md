# Decisiones de arquitectura (ADR)

Cada ADR registra una decisión en pocas líneas: el contexto, la decisión y sus consecuencias.

| # | Decisión | Semana |
|---|---|---|
| [0001](0001-alembic-y-migraciones.md) | Alembic para el esquema; fin de `create_all` | Fase 0 |
| [0002](0002-rls-una-base.md) | Una sola base Postgres con RLS forzado (reemplaza "una base por tenant") | 1 |
| [0003](0003-identidad-y-roles.md) | Identidad, roles y conexión de la app (`app_user`, contexto por transacción) | 1 |
| [0004](0004-auditoria-y-limite-de-peticiones.md) | Auditoría de accesos (CU-13) y límite de peticiones | 1 |
| [0005](0005-consentimiento-plan-y-cuestionario.md) | Consentimiento versionado, plan simulado y cuestionario (CU-01) | 2 |
| [0006](0006-inferencia-litert.md) | Inferencia con LiteRT y mapa de calor CAM en numpy | 2 |
| [0007](0007-recordatorios-en-control.md) | Recordatorios en `control` y despachador sin contexto clínico (CU-05) | 3 |
| [0008](0008-administracion-de-tenants-y-usuarios.md) | Administración de tenants y usuarios (CU-12) | 3 |
| [0009](0009-fichas-de-institucion-y-acceso-clinico-por-rol.md) | Fichas de institución, acceso clínico por rol y traspaso entre médicas | 4 |
| [0010](0010-paquete-compartido-cifrado.md) | Paquete compartido cifrado e importación (CU-07, CU-08) | 4 |
| [0011](0011-dicom-y-perfiles-del-modelo.md) | DICOM y perfiles del modelo (CU-09) | 4 |
| [0012](0012-panel-y-caso-de-la-medica.md) | Panel y caso de la médica (CU-11, CU-08) | 4 |
| [0013](0013-memoria-y-hosting.md) | Memoria con el modelo cargado y decisión de hosting | 5 |
| [0014](0014-tarjeta-calibracion-y-umbrales.md) | Tarjeta del modelo v2, calibración y umbrales | 5 |
| [0015](0015-reportes-pdf-y-hl7.md) | Reportes PDF y HL7 v2 simulado (CU-10) | 5 |
| [0016](0016-despliegue-estable-y-endurecimiento.md) | Despliegue estable y endurecimiento | 5 |

Documentos relacionados: [arquitectura de multitenencia](../arquitectura-multitenencia.md),
[despliegue](../despliegue.md), [migración de hosting](../migracion-hosting.md),
[integración HL7](../hl7-integracion.md) y [limitaciones conocidas](../limitaciones-conocidas.md).
