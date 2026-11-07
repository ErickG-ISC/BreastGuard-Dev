# Limitaciones conocidas

Lo que BreastGuard **no** hace o hace de forma limitada, al cierre de la Semana 5. Es un
proyecto escolar: herramienta de apoyo al diagnóstico, nunca un diagnóstico.

## Modelo y resultados
- **Modelo de demostración.** Hoy corre un EfficientNet-B0 **sin entrenar** (`is_demo: true`): sus resultados no tienen validez. El camino para integrar el modelo real está listo (ADR 0014), pero el modelo no existe todavía.
- **Mastografía de prototipo.** Un modelo entrenado con ecografías (BUSI) **no es válido para mastografías**. El perfil `mastografia_prototipo` lleva siempre el aviso. Un modelo real requeriría otro dataset (CBIS-DDSM, INbreast, VinDr-Mammo).
- **BI-RADS** lo asigna siempre la médica; el modelo no lo sugiere.
- **DICOM:**
  - no se admite JPEG Lossless (su decodificador libre es GPL);
  - se rechazan los estudios con anotaciones grabadas (`BurnedInAnnotation`);
  - si el DICOM no lo declara, el servidor no detecta datos grabados en los píxeles: la médica lo confirma en cada subida.

## Interoperabilidad
- **HL7 v2 simulado.** El ORU^R01 es estructuralmente válido, pero no se ha probado contra ningún sistema hospitalario. Lleva códigos locales y `MSH-11 = T`. Lo que faltaría está en `docs/hl7-integracion.md`. No hay FHIR.

## Infraestructura
- **Render gratuito:**
  - 512 MB de RAM: el peor caso medido es 419 MB (ADR 0013);
  - se duerme tras unos 15 minutos sin tráfico: el primer acceso tarda alrededor de 1 minuto.
- **Límite de peticiones en memoria:** vale para una sola instancia. Con varias haría falta un almacén compartido (Redis). El límite es por IP, no por usuario.
- **Objetos huérfanos en Storage:** si falla la base después de subir a Storage, se intenta borrar lo subido, pero puede quedar algún objeto si también falla el borrado.
- **Correo:** Resend sin dominio verificado solo entrega al correo dueño de la cuenta.
- **Purga de tenants:** desde la UI solo se solicita. La ejecuta una persona con `purge_tenant.py --pending`.
- **Sin respaldos a un punto en el tiempo** (plan gratuito de Supabase): antes de la demo se hace un `pg_dump` a mano.

## Seguridad: riesgos aceptados
| Aviso | Paquete | Por qué no aplica hoy | Salida |
|---|---|---|---|
| GHSA-3qf3-8w2g-rqmx (PYSEC-2026-4298) | `python-jose` 3.5.0 | Requiere que la app verifique con una llave **pública** y sin restringir algoritmos. BreastGuard usa solo HS256 con un secreto simétrico y `algorithms=["HS256"]` | Migrar a PyJWT, un cambio pequeño en `services/auth.py` y `unsubscribe.py`. Queda propuesto, no hecho, para no tocar la autenticación antes de la demo |
| CVE-2024-23342 (PYSEC-2026-1325) | `ecdsa` 0.19.2 (dependencia de python-jose) | Ataque de tiempo al **firmar** con ECDSA P-256. La app nunca firma con ECDSA | Desaparece al migrar a PyJWT |
| 2 bajas y 4 moderadas de npm | `vite-plugin-pwa` → `workbox-build`, `glob`, `minimatch`, `deepmerge`, `@rollup/plugin-node-resolve` | Solo se usan al **compilar** la PWA; nada llega al navegador | Actualizar cuando `vite-plugin-pwa` publique una versión compatible (la sugerencia de npm es bajar una versión mayor) |

## Producto
- **`/images`** sigue aceptando personal (devuelve vacío o 404 por RLS); restringirlo a pacientes rompe pruebas de la Semana 1 y quedó pendiente.
- **Contenido médico** (blog, autoexploración, consentimientos) en borrador, pendiente de revisión: `docs/contenido-pendiente-de-revision.md`.
- **Pagos y planes simulados.** No hay cobro real.
- **`legacy.users`** conserva datos del prototipo; hay que borrar el esquema `legacy` cuando ya no haga falta.
- **Notificaciones push** no implementadas (solo correo y avisos dentro de la app).
