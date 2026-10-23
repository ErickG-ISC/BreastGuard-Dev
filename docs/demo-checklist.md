# Lista de verificación de la demo (Semanas 1 y 2)

## Antes (30 min antes)
- [ ] Abrir `https://<api>/api/v1/health` para **despertar Render** (~1 min). Debe decir `model: loaded`.
- [ ] Abrir el frontend en el celular y en la laptop.
- [ ] Tener a mano **2 o 3 ecografías públicas** (dataset BUSI) en el celular. **Nunca imágenes de pacientes reales.**
- [ ] Tener una foto a color cualquiera, para mostrar el rechazo.
- [ ] Iniciar sesión como `platform_admin` en la laptop.
- [ ] Tener creadas de antemano: una paciente de **otro tenant** y un `tenant_admin` (para los pasos 5 y 6).
- [ ] Haber verificado una vez que la IP de la auditoría es la real (ver docs/despliegue.md).

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
7. **Autoexploración y diario (CU-03, CU-04):**
   1. En **Más → Autoexploración**, recorrer los 6 pasos y responder "Sí, noté algo distinto".
   2. Pulsar **Registrar en el diario**: el formulario ya trae la fecha y el enlace a la autoexploración. Tocar la zona en el **mapa corporal** (también funciona con teclado), elegir síntomas e intensidad y guardar.
   3. En **Línea de tiempo**, filtrar por zona y mostrar la marca de "en periodo".
8. **Recordatorios (CU-05):**
   1. En **Más → Recordatorios**, activar la autoexploración (primer domingo del mes) con "Ambos" y el modo discreto.
   2. Antes de la demo, dejar un recordatorio **vencido** (o configurarlo para el siguiente cuarto de hora) y lanzar el workflow **Recordatorios** con *Run workflow* en GitHub (o esperar el cron de 15 minutos).
   3. Mostrar la **campana** con el aviso y la tarjeta en Inicio. En los logs de Render aparece "Correo (consola)" con el destinatario enmascarado.
9. **Información (CU-06):** abrir **Más → Información**: "Recomendado para ti" cambia según el último análisis; cada artículo dice "Contenido educativo general · borrador" y lista sus fuentes.

## Mensajes clave
- "Es una **herramienta de apoyo**; no sustituye el criterio ni la consulta médica."
- "El modelo actual es **de demostración** (sin entrenar); el real se entrena aparte y se cambia sin tocar código: es subir un archivo y cambiar `MODEL_PREFIX`."
- "Cada institución está aislada por la base de datos misma (RLS forzado), no solo por el código."
- "Los recordatorios viven fuera de los datos clínicos: el proceso que los envía **no puede ver** información de salud (ADR 0007)."
