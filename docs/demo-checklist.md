# Lista de verificación de la demo (Semanas 1 y 2)

## Antes (30 min antes)
- [ ] Abrir `https://<api>/api/v1/health` para **despertar Render** (~1 min). Debe decir `model: loaded`.
- [ ] Abrir el frontend en el celular y en la laptop.
- [ ] Tener a mano **2 o 3 ecografías públicas** (dataset BUSI) en el celular. **Nunca imágenes de pacientes reales.**
- [ ] Tener una foto a color cualquiera, para mostrar el rechazo.
- [ ] Iniciar sesión como `platform_admin` en la laptop.

## Guion
1. **Multitenencia (CU-12):** como `platform_admin`, en **Tenants**, ir a **Nueva institución**. Se abre el **chequeo de aislamiento**, que debe salir todo en verde y concluyente.
2. **Registro (CU-01), en el celular:**
   1. Ir a **Crear cuenta**, llenar los datos y aceptar el **consentimiento**: mostrar que sin la casilla no se puede avanzar.
   2. Elegir un plan y señalar el aviso "Simulación".
   3. Responder el cuestionario. Se muestran los **factores a comentar con tu médico**, sin ninguna probabilidad.
3. **Análisis (CU-02):**
   1. Ir a **Subir ecografía**, elegir una de la galería (o tomar una foto de la pantalla) y pulsar **Analizar**.
   2. En el resultado, mostrar:
      - el reporte en lenguaje sencillo;
      - la confianza en palabras;
      - el heatmap y su **control de opacidad**;
      - el aviso **"modelo de demostración"** y el de herramienta de apoyo.
   3. Subir la foto a color: se **rechaza** con un mensaje claro.
4. **Historial y eliminación:** en **Historial**, eliminar un análisis. Explicar que también se borran la imagen y el heatmap de Storage.
5. **Aislamiento:**
   1. Iniciar sesión con una paciente de **otro tenant** y abrir la URL `/resultado/<id>` de la primera paciente: responde **"Análisis no encontrado"**.
   2. Mostrar que el intento quedó auditado (`analysis.denied`) en el log del tenant que preguntó.
6. **Auditoría (CU-13):** como `tenant_admin` de la institución, `GET /api/v1/audit` muestra solo la actividad de su tenant.

## Mensajes clave
- "Es una **herramienta de apoyo**; no sustituye el criterio ni la consulta médica."
- "El modelo actual es **de demostración** (sin entrenar); el real se entrena aparte y se cambia sin tocar código: es subir un archivo y cambiar `MODEL_PREFIX`."
- "Cada institución está aislada por la base de datos misma (RLS forzado), no solo por el código."
