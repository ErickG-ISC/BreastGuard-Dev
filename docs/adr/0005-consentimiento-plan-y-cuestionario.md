# ADR 0005 — Consentimiento, plan simulado y cuestionario (CU-01)

- Estado: aceptado (Semana 2, 2026-10-22)

## Decisión
- **Consentimiento informado** en `control.consents`, ligado al usuario.
  - Guarda la versión, el sha256 del texto aceptado, la fecha y la IP.
  - El texto vive en el repo (`backend/app/content/consent_v1.md`, borrador académico) y se sirve en `GET /consent/current`.
  - `/auth/register` exige `consent_accepted: true` y la versión vigente; si no, responde 422 y no crea nada.
  - Cuenta, consentimiento, suscripción y ficha clínica se crean en una sola transacción.
  - `app_user` solo puede hacer `SELECT` e `INSERT` sobre los consentimientos: no se editan ni se borran.
- **Planes simulados** en `control.plans`, con suscripción en `control.subscriptions` (`status = 'simulada'` por CHECK).
  - No hay pasarela de pago ni datos de tarjeta, y la interfaz lo dice.
  - Los planes no limitan el uso.
- **Cuestionario de antecedentes** en `clinical.questionnaires`.
  - Usa RLS forzado y la política "paciente solo lo suyo" (`add_patient_owner_policy`).
  - Guarda las respuestas y la versión. Es de solo inserción: cada envío es un registro nuevo.
- **Factores a comentar con el médico** con reglas simples y legibles en `backend/app/content/risk_rules.py`: edad de tamizaje (40, NOM-041), antecedentes familiares, BRCA, biopsia previa, terapia hormonal, revisiones atrasadas y síntomas actuales.
  - El resultado es una lista de factores y un nivel (`sin_factores`, `factores_a_comentar`, `sintomas_a_consultar`).
  - **Nunca es una probabilidad ni un diagnóstico.**

## Consecuencias
- Cambiar el texto del consentimiento exige una versión nueva: los usuarios existentes conservan la que aceptaron.
- El texto y las reglas son borradores académicos; deben revisarse con un profesional de la salud antes de cualquier uso real.
- La eliminación de cuenta se atiende a petición (el texto lo explica). La eliminación de análisis llega con CU-02.
