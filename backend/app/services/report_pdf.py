"""PDF de los reportes (CU-10, ADR 0015), generado en el servidor con fpdf2 y DejaVu Sans (Unicode).

- Médica: institución, paciente (nombre y edad aproximada), fecha del estudio, clase y confianza
  del modelo, mapa de calor, BI-RADS y recomendación DE LA MÉDICA, autora, id del reporte y
  fecha, y los avisos (herramienta de apoyo, prototipo de mastografía, modelo de demostración).
- Paciente: su reporte en lenguaje sencillo tal como se guardó, el mapa de calor y los avisos.

Los metadatos del PDF (título, autor) no llevan datos personales. El texto viene de la base y se
escribe como texto plano (fpdf2 no interpreta HTML ni markdown aquí).
"""

import io
from datetime import UTC
from pathlib import Path

from fpdf import FPDF
from PIL import Image

from backend.app.services.reports import ReportData

FONTS = Path(__file__).resolve().parents[1] / "content" / "fonts"
CLASS_TEXT = {"normal": "Normal", "benigno": "Benigno", "maligno": "Maligno"}
STATUS_TEXT = {"completed": "Completado", "inconclusive": "No concluyente"}
IMAGE_MAX_MM = (120, 95)  # ancho, alto
IMAGE_MAX_PX = 1024


def _reduced(png: bytes) -> Image.Image:
    """El mapa de una mastografía mide hasta 2048 px; a 120 mm bastan 1024 px (> 200 dpi).

    Reducirlo antes de incrustarlo baja la memoria y el tamaño del PDF (ADR 0015).
    """
    with Image.open(io.BytesIO(png)) as source:
        image = source.convert("RGB")
    image.thumbnail((IMAGE_MAX_PX, IMAGE_MAX_PX), Image.Resampling.LANCZOS)
    return image


def _date(moment) -> str:
    return moment.astimezone(UTC).strftime("%d/%m/%Y %H:%M UTC")


class _Report(FPDF):
    def __init__(self, data: ReportData, title: str) -> None:
        super().__init__(format="A4")
        self.data = data
        self.doc_title = title
        self.add_font("DejaVu", "", str(FONTS / "DejaVuSans.ttf"))
        self.add_font("DejaVu", "B", str(FONTS / "DejaVuSans-Bold.ttf"))
        self.set_title(title)  # genérico: sin nombre de la paciente
        self.set_author("BreastGuard")
        self.set_creator("BreastGuard")
        self.set_margins(15, 15, 15)
        self.set_auto_page_break(True, margin=22)
        self.add_page()

    def header(self) -> None:
        self.set_font("DejaVu", "B", 13)
        self.cell(0, 7, self.doc_title, new_x="LMARGIN", new_y="NEXT")
        self.set_font("DejaVu", "", 9)
        self.cell(0, 5, self.data.institution, new_x="LMARGIN", new_y="NEXT")
        self.ln(2)

    def footer(self) -> None:
        self.set_y(-18)
        self.set_font("DejaVu", "", 7)
        self.multi_cell(
            0,
            3.5,
            f"Reporte {self.data.report_id} · emitido {_date(self.data.issued_at)} · "
            f"página {self.page_no()}\n{self.data.warnings[0]}",
            align="C",
        )

    def section(self, title: str) -> None:
        self.ln(2)
        self.set_font("DejaVu", "B", 11)
        self.cell(0, 6, title, new_x="LMARGIN", new_y="NEXT")
        self.set_font("DejaVu", "", 10)

    def field(self, label: str, value: str) -> None:
        self.set_font("DejaVu", "B", 10)
        self.cell(48, 5.5, f"{label}:")
        self.set_font("DejaVu", "", 10)
        self.multi_cell(0, 5.5, value, new_x="LMARGIN", new_y="NEXT")

    def warnings(self) -> None:
        self.set_fill_color(255, 244, 229)
        self.set_font("DejaVu", "B", 9)
        self.multi_cell(
            0,
            4.5,
            "\n".join(self.data.warnings),
            border=1,
            fill=True,
            new_x="LMARGIN",
            new_y="NEXT",
        )
        self.set_font("DejaVu", "", 10)

    def heatmap(self) -> None:
        if not self.data.heatmap_png:
            return
        self.section("Mapa de calor del modelo")
        max_w, max_h = IMAGE_MAX_MM
        if self.get_y() + max_h > self.h - 25:
            self.add_page()
        info = self.image(
            _reduced(self.data.heatmap_png),
            x=self.l_margin,
            y=self.get_y(),
            w=max_w,
            h=max_h,
            keep_aspect_ratio=True,
        )
        self.set_y(self.get_y() + info.rendered_height + 2)
        self.set_font("DejaVu", "", 8)
        self.multi_cell(
            0,
            4,
            "Zonas en las que se fijó el modelo. No marcan una lesión ni un diagnóstico.",
            new_x="LMARGIN",
            new_y="NEXT",
        )
        self.set_font("DejaVu", "", 10)


def _common(pdf: _Report) -> None:
    data = pdf.data
    pdf.warnings()
    pdf.section("Paciente")
    pdf.field("Nombre", data.patient_name)
    pdf.field("Edad aproximada", f"{data.approx_age} años" if data.approx_age is not None else "—")
    pdf.section("Estudio")
    pdf.field("Fecha del estudio", _date(data.study_date))
    pdf.field("Tipo", data.profile_label)


def doctor_pdf(data: ReportData) -> bytes:
    pdf = _Report(data, "Reporte técnico de apoyo al diagnóstico")
    _common(pdf)
    pdf.section("Resultado del modelo (apoyo, no diagnóstico)")
    pdf.field("Clase estimada", CLASS_TEXT.get(data.predicted_class, data.predicted_class))
    pdf.field("Confianza", f"{data.confidence * 100:.1f} %")
    pdf.field("Estado", STATUS_TEXT.get(data.analysis_status, data.analysis_status))
    pdf.field("Versión del modelo", data.model_version)
    pdf.heatmap()
    pdf.section("Valoración de la médica")
    pdf.field("Categoría BI-RADS", data.birads or "—")
    pdf.field("Recomendación", data.recommendation or "—")
    pdf.field("Revisado por", data.reviewer_name or "—")
    if data.reviewed_at:
        pdf.field("Fecha de revisión", _date(data.reviewed_at))
    pdf.set_font("DejaVu", "", 8)
    pdf.ln(1)
    pdf.multi_cell(
        0,
        4,
        "La categoría BI-RADS y la recomendación las asignó la médica; el modelo no las sugiere.",
        new_x="LMARGIN",
        new_y="NEXT",
    )
    return bytes(pdf.output())


def patient_pdf(data: ReportData) -> bytes:
    report = data.plain_report or {}
    pdf = _Report(data, "Tu resultado de BreastGuard")
    _common(pdf)
    pdf.section(report.get("title") or "Resultado")
    for paragraph in report.get("paragraphs") or []:
        pdf.multi_cell(0, 5.5, paragraph, new_x="LMARGIN", new_y="NEXT")
        pdf.ln(1)
    if report.get("recommendation"):
        pdf.field("Qué hacer", report["recommendation"])
    pdf.field("Versión del modelo", data.model_version)
    pdf.heatmap()
    return bytes(pdf.output())
