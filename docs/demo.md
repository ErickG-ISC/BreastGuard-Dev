# Guion de la demo

Guion de la presentación final, en 15 minutos aproximadamente, alineado con "Demo final" de
CLAUDE.md. Todo con **datos sintéticos**: ninguna imagen ni dato de pacientes reales.

## Lista previa

### El día anterior

- [ ] **Migraciones aplicadas** en la base de desarrollo:
  `alembic -c backend/alembic.ini current` debe decir `0019 (head)`. Si no, `upgrade head`. Después del despliegue, `/api/v1/health` debe decir `"migration": "ok"`.
- [ ] **CI en verde** en `main`, incluido el workflow E2E.
- [ ] **Guarda de los scripts de demo:** todos exigen `BREASTGUARD_ENV=development` y
  `DEMO_DB_REF=<ref>`, el identificador de la base de desarrollo. Con el pooler de Supabase es el
  sufijo del usuario `postgres.<ref>`. Si no coincide, el script se niega y muestra el valor de
  `DATABASE_URL`.
- [ ] **Datos de demo regenerados** por el flujo real; solo crea cuentas `@demo.invalid` y copias
  en tenants `demo-…`:
  ```
  BREASTGUARD_ENV=development DEMO_DB_REF=<ref> python -m backend.scripts.demo_flow --create --slug demo-clinica-norte --doctor-email demo-clinica-norte-doctor-1@example.com
  ```
- [ ] **Credenciales de demo**, emitidas por ti en tu terminal. Se imprimen una sola vez: anótalas
  fuera del repositorio.
  ```
  BREASTGUARD_ENV=development DEMO_DB_REF=<ref> python -m backend.scripts.demo_credentials --issue \
    --email demo-clinica-norte-doctor-1@example.com \
    --email demo-hospital-sur-doctor-1@example.com \
    --email <una paciente demo-paciente-…@demo.invalid>
  ```
  Las pacientes demo están en la base (`control.users`, correo que termina en `@demo.invalid`).
- [ ] **Sin contraseñas débiles:**
  `BREASTGUARD_ENV=development DEMO_DB_REF=<ref> python -m backend.scripts.demo_credentials --check` debe terminar
  sin cuentas débiles.
- [ ] **Respaldo de la base** antes de la demo. El plan gratuito de Supabase no tiene respaldos a
  un punto en el tiempo:
  ```
  pg_dump "$DATABASE_URL" -Fc -f ~/respaldos-breastguard/antes-de-demo.dump
  ```
  Escríbelo fuera del repo (`*.dump` también está en `.gitignore`). Contiene hashes y todos los
  datos de la base: bórralo cuando ya no lo necesites.
- [ ] **Material del plan B listo** (ver abajo).

### Una hora antes

- [ ] **Despertar Render:** abre `https://<tu-api>/api/v1/health` y espera `"status": "ok"`, `"migration": "ok"` y `"model": "loaded"`.
- [ ] **Smoke test** (solo lectura, sin login):
  `python -m backend.scripts.smoke_deployed --api https://<tu-api>.onrender.com --web https://<tu-app>.vercel.app`
  debe terminar sin fallas.
  El plan gratuito tarda ~1 minuto en despertar. Repite 5 minutos antes de empezar.
- [ ] **Frontend de Vercel** abierto y con sesión cerrada.
- [ ] **Tres ventanas o perfiles del navegador** (sesiones separadas), cada una con su sesión:
  - paciente demo (B2C);
  - doctora de la clínica Norte;
  - administradora de plataforma.
- [ ] **Una ecografía sintética** a mano (las de las pruebas o una pública del dataset BUSI) y un
  **DICOM sintético**, generado con `tests/dicom_helpers.make_dicom`.

## Guion (≈ 15 min)

| # | Tiempo | Quién | Qué se muestra |
|---|---|---|---|
| 0 | 1 min | — | Qué es BreastGuard y el aviso: herramienta de apoyo, no diagnóstico. |
| 1 | 3 min | Admin de plataforma | **Alta de tenant en vivo** (`/admin/tenants` → "Alta de tenant"). El chequeo de aislamiento se abre solo: 5 verificaciones en verde, ejecutadas como el rol de la app (sin superusuario) y en solo lectura. Explicar: una base, RLS forzado, un tenant no ve filas de otro. |
| 2 | 3 min | Paciente B2C | Sube la ecografía en "Analizar" y recibe la predicción, el mapa de calor y el reporte sencillo con el aviso. Opcional: diario y recordatorios. |
| 3 | 4 min | Paciente → doctora | **Compartir:** "Compartir con mi médica", elegir el análisis, aceptar el consentimiento y obtener el código y el QR. La doctora (otra ventana) va a "Importar paquete", pega el código, abre el caso desde el panel ("Casos sospechosos"), ve la línea de tiempo y el mapa de calor, escribe una nota y marca revisado. La paciente ve "Importado por…" en "Mis paquetes". Mostrar que el **segundo uso del código falla**. |
| 4 | 2 min | Doctora de otro tenant | **Aislamiento:** con la doctora del Hospital Sur, el panel está vacío y pegar la URL del caso de la Norte da "Paciente no encontrada". |
| 5 | 2 min | Doctora | **Extra, si hay tiempo:** en el caso, "Agregar estudio" con el DICOM sintético. Aparece el aviso de prototipo y la doctora asigna el BI-RADS (el modelo no lo sugiere). |
| 6 | 1 min | Doctora | **Extra (CU-10):** en el caso revisado, "Descargar PDF" y "Descargar HL7" (simulación, no probada contra un sistema hospitalario). El id del reporte coincide con la exportación en la bitácora. |
| — | resto | — | Preguntas. |

Frases clave:
- "El modelo es de demostración; las métricas reales llegan con el modelo entrenado."
- "Nunca guardamos el DICOM original ni datos personales del estudio."
- "La copia que importa la doctora es de su institución; el código sirve una sola vez."

## Plan B

**Si falla la red o Render:**
1. **Grabación:** graba el día anterior el guion completo con la grabadora de pantalla del sistema
   (Windows: `Win + Alt + R`) y tenla en el escritorio.
2. **Capturas:** una por paso, en una carpeta local, en el orden del guion.
3. **Demo local sin internet:** las pruebas E2E levantan todo en la laptop (Postgres en Docker,
   backend y frontend) y recorren los tres flujos en un navegador visible:
   ```
   docker compose up -d db
   E2E_HEADED=1 pytest e2e -q
   ```
   Requiere tener instalado lo de `requirements-e2e.txt` y `python -m playwright install chromium`.

**Si falla solo una parte:**
- **El análisis tarda o da 503:** el modelo puede estar despertando. Usar un caso ya importado
  por el escenario demo (Marisol Vega y Daniela Ruiz son sospechosas).
- **El correo no llega:** es esperado (Resend sin dominio verificado). La importación no
  depende del correo; el código se copia o se escanea el QR.

## Después de la demo

- [ ] Bloquear las cuentas sintéticas:
  `BREASTGUARD_ENV=development DEMO_DB_REF=<ref> python -m backend.scripts.demo_credentials --lock`.
- [ ] Si se crearon tenants en vivo, solicitar su purga desde la UI y ejecutarla con
  `purge_tenant.py --pending`.
- [ ] Opcional, limpiar el escenario demo:
  `BREASTGUARD_ENV=development DEMO_DB_REF=<ref> python -m backend.scripts.demo_flow --clean`.
