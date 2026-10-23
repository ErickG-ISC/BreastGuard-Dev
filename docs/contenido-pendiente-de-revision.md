# Contenido médico pendiente de revisión

Todo el contenido educativo de BreastGuard es un **BORRADOR académico** escrito sin revisión de
personal de salud. Hasta que alguien lo revise, la app muestra "Contenido educativo general ·
borrador" y nunca "validado". Al revisarlo, llena `revisado_por` y `fecha_revision` y cambia
`estado: revisado` en el archivo (las pruebas lo exigen).

| Archivo | Qué verificar |
|---|---|
| `backend/app/content/consent_v1.md` | Texto legal del consentimiento y contacto de privacidad (hoy `privacidad@breastguard.example`). |
| `backend/app/content/risk_rules.py` | Factores y edad de tamizaje (40 años, NOM-041-SSA2-2011). |
| `backend/app/content/self_exam_v1.json` | Pasos de la autoexploración, momento del ciclo recomendado y signos a observar. |
| `blog/bi-rads-3.md` | Definición de BI-RADS 3 ("probablemente benigno") y que lo habitual es seguimiento de control; contrastar con el atlas BI-RADS del ACR. Confirmar la URL del ACR (cambia con frecuencia). |
| `blog/como-funciona-la-ecografia.md` | Usos de la ecografía y su relación con la mastografía. |
| `blog/autoexploracion-y-autoconocimiento.md` | Frecuencia mensual, momento del ciclo y que no sustituye la exploración clínica. |
| `blog/cuando-consultar.md` | Lista de signos que ameritan consulta pronta. |
| `blog/que-hace-y-que-no-hace-la-app.md` | Que la descripción del modelo y de la privacidad siga siendo cierta. |
| `blog/faq.md` | Respuestas sobre privacidad y tipos de imagen. |

Fuentes citadas (verificar que sigan vigentes):

- OMS, nota descriptiva "Cáncer de mama": https://www.who.int/es/news-room/fact-sheets/detail/breast-cancer
- NOM-041-SSA2-2011 (DOF, 09/06/2011): https://www.dof.gob.mx/nota_detalle.php?codigo=5194157&fecha=09/06/2011
- IMSS, "Cáncer de mama": https://www.imss.gob.mx/salud-en-linea/cancer-mama
- ACR BI-RADS Atlas: https://www.acr.org/Clinical-Resources/Clinical-Tools-and-Reference/Reporting-and-Data-Systems/BI-RADS
- Al-Dhabyani et al., "Dataset of breast ultrasound images" (BUSI), Data in Brief 2020: https://doi.org/10.1016/j.dib.2019.104863

El contenido no incluye cifras ni porcentajes propios; una prueba (`tests/api/test_blog.py`)
falla si aparece un porcentaje o una afirmación como "detecta el cáncer" o "validado
médicamente".
