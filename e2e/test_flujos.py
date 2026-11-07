"""Flujos completos en el navegador (local o CI; nunca contra Render). Datos sintéticos.

(a) La paciente comparte; la doctora importa, abre el caso, escribe una nota y marca revisado.
(b) La administradora de plataforma da de alta un tenant y ejecuta el chequeo de aislamiento.
(c) Una médica y una administradora de OTRO tenant no acceden a nada de lo anterior.
"""

import re
import uuid

from playwright.sync_api import expect

from e2e.conftest import API, WEB, ultrasound
from tests.helpers import DEFAULT_PASSWORD, auth_headers, insert_tenant, insert_user

SUSPICIOUS = {"normal": 0.05, "benigno": 0.1, "maligno": 0.85}


def login(page, email: str, landing: str) -> None:
    page.goto(f"{WEB}/login")
    page.get_by_label("Email").fill(email)
    page.get_by_label("Contraseña").fill(DEFAULT_PASSWORD)
    page.get_by_role("button", name="Entrar").click()
    page.wait_for_url(f"**{landing}")


class _B2C:
    def __init__(self, stack):
        self.id = stack.sql("SELECT id FROM control.tenants WHERE slug = 'b2c'").scalar_one()


def patient_with_analysis(stack, name: str):
    patient = insert_user(stack.owner, _B2C(stack), role="patient")
    stack.sql(
        "UPDATE clinical.patients SET display_name = :n WHERE user_id = :u", n=name, u=patient.id
    )
    stack.predictor.probabilities = SUSPICIOUS
    response = stack.http.post(
        f"{API}/analyses",
        files={"file": ("eco.png", ultrasound(7), "image/png")},
        headers=auth_headers(patient),
    )
    response.raise_for_status()
    return patient, response.json()["id"]


def share_and_import_by_api(stack, patient, analysis_id, doctor) -> uuid.UUID:
    consent = stack.http.get(f"{API}/shares/consent", headers=auth_headers(patient)).json()
    created = stack.http.post(
        f"{API}/shares",
        json={
            "analysis_ids": [analysis_id],
            "include_identity": True,
            "consent_accepted": True,
            "consent_version": consent["version"],
        },
        headers=auth_headers(patient),
    )
    created.raise_for_status()
    imported = stack.http.post(
        f"{API}/doctor/shares/import",
        json={"code": created.json()["code"]},
        headers=auth_headers(doctor),
    )
    imported.raise_for_status()
    return uuid.UUID(imported.json()["patient_id"])


def test_a_compartir_importar_revisar(stack, new_page):
    name = "María Sintética A"
    patient, _ = patient_with_analysis(stack, name)
    clinic = insert_tenant(stack.owner, "clinica-e2e-a")
    doctor = insert_user(stack.owner, clinic, role="doctor")

    # La paciente, en el teléfono (390 px), crea el paquete y copia el código
    phone = new_page(390, 844)
    login(phone, patient.email, "/paciente")
    phone.goto(f"{WEB}/compartir")
    phone.locator("fieldset").first.get_by_role("checkbox").first.check()
    # Sin esto la copia llega como "Paciente importada el …" (privado por defecto)
    phone.get_by_label("Mi nombre y mi edad").check()
    phone.get_by_label("Leí y acepto compartir esta copia con mi médica y su institución.").check()
    phone.get_by_role("button", name="Crear código").click()
    code_box = phone.get_by_label("Código del paquete")
    expect(code_box).to_have_text(re.compile(r"^[0-9A-Z]{5}(-[0-9A-Z]{5}){3}-[0-9A-Z]{6}$"))
    code = code_box.inner_text()

    # La médica, en escritorio, importa con el código
    desk = new_page()
    login(desk, doctor.email, "/medico")
    # Botón-enlace del panel (el de la barra lateral lleva el mismo nombre)
    desk.get_by_role("link", name="Importar paquete").last.click()
    desk.get_by_label("Código").fill(code)
    desk.get_by_role("button", name="Importar", exact=True).click()
    expect(desk.get_by_text("Paciente importada")).to_be_visible()

    # Panel: aparece entre los casos sospechosos; abre el caso
    desk.get_by_role("link", name="Volver al inicio").click()
    desk.get_by_role("tab", name="Casos sospechosos").click()
    row = desk.get_by_role("row").filter(has_text=name)
    expect(row).to_contain_text("Sospechoso")
    row.get_by_role("button", name="Revisar").click()
    desk.wait_for_url("**/medico/pacientes/**")
    expect(desk.get_by_role("heading", name=re.compile(name))).to_be_visible()

    # Nota y marcar revisado
    desk.get_by_label("Escribe una nota").fill("Solicitar biopsia guiada por ecografía.")
    desk.get_by_role("button", name="Guardar nota").click()
    expect(desk.get_by_text("Solicitar biopsia guiada por ecografía.")).to_be_visible()
    desk.get_by_role("button", name="Marcar revisado").click()
    expect(desk.get_by_text(re.compile("^Revisado por"))).to_be_visible()

    row = stack.sql(
        "SELECT p.status, count(n.id) AS notes FROM clinical.patients p "
        "LEFT JOIN clinical.case_notes n ON n.patient_id = p.id "
        "WHERE p.tenant_id = :t GROUP BY p.status",
        t=clinic.id,
    ).one()
    assert row.status == "revisado" and row.notes == 1

    # La paciente ve en "Mis paquetes" quién importó su copia
    phone.goto(f"{WEB}/compartidos")
    expect(phone.get_by_text(re.compile("Importado por"))).to_be_visible()


def test_b_alta_de_tenant_y_chequeo_de_aislamiento(stack, new_page):
    # Filas testigo en otros tenants para que el chequeo sea concluyente
    patient_with_analysis(stack, "Testigo B2C")
    admin = insert_user(stack.owner, None, role="platform_admin")
    slug = f"clinica-e2e-{uuid.uuid4().hex[:6]}"

    page = new_page()
    login(page, admin.email, "/admin/tenants")
    page.get_by_role("button", name="Alta de tenant").click()
    page.get_by_label("Nombre de la institución").fill("Clínica de Prueba E2E")
    page.get_by_label("Identificador (slug)").fill(slug)
    page.get_by_label("Nombre completo").fill("Administradora E2E")
    page.get_by_label("Correo del primer administrador").fill(f"admin-{slug}@example.com")
    page.get_by_role("button", name="Crear tenant").click()
    expect(page.get_by_text("Resultado del alta: Clínica de Prueba E2E")).to_be_visible()

    # Tras el alta el chequeo se abre solo (también hay un botón "Ver chequeo de aislamiento")
    dialog = page.get_by_role("dialog")
    expect(dialog.get_by_text(re.compile("Chequeo de aislamiento: " + slug))).to_be_visible()
    expect(dialog.get_by_text("Aislamiento verificado")).to_be_visible()
    expect(dialog.get_by_text("Falla")).to_have_count(0)


def test_c_otro_tenant_no_accede(stack, new_page):
    name = "Ana Sintética C"
    patient, analysis_id = patient_with_analysis(stack, name)
    clinic_a = insert_tenant(stack.owner, "clinica-e2e-c1")
    doctor_a = insert_user(stack.owner, clinic_a, role="doctor")
    pid = share_and_import_by_api(stack, patient, analysis_id, doctor_a)

    clinic_b = insert_tenant(stack.owner, "clinica-e2e-c2")
    doctor_b = insert_user(stack.owner, clinic_b, role="doctor")
    admin_b = insert_user(stack.owner, clinic_b, role="tenant_admin")

    # Médica de otro tenant: panel vacío y el caso por URL da "no encontrada"
    page = new_page()
    login(page, doctor_b.email, "/medico")
    expect(page.get_by_text("No hay pacientes con este filtro.")).to_be_visible()
    expect(page.get_by_text(name)).to_have_count(0)
    page.goto(f"{WEB}/medico/pacientes/{pid}")
    expect(page.get_by_text("Paciente no encontrada")).to_be_visible()

    # Mismas respuestas en la API que para un id inexistente; nada en los contadores
    foreign = stack.http.get(f"{API}/doctor/patients/{pid}", headers=auth_headers(doctor_b))
    missing = stack.http.get(
        f"{API}/doctor/patients/{uuid.uuid4()}", headers=auth_headers(doctor_b)
    )
    assert foreign.status_code == missing.status_code == 404
    assert foreign.json() == missing.json()
    summary = stack.http.get(f"{API}/doctor/patients/summary", headers=auth_headers(doctor_b))
    assert summary.json()["active"] == 0

    # Administradora de otro tenant: ni datos clínicos ni el personal de la clínica A
    admin_page = new_page()
    login(admin_page, admin_b.email, "/institucion/usuarios")
    expect(admin_page.get_by_text(doctor_a.email)).to_have_count(0)
    clinical = stack.http.get(f"{API}/doctor/patients/{pid}", headers=auth_headers(admin_b))
    assert clinical.status_code == 403


def test_d_acerca_del_modelo_en_movil(stack, new_page):
    """Página pública: solo lo que trae la ficha y el aviso de mastografía, a 390 px."""
    page = new_page(390, 844)
    page.goto(f"{WEB}/acerca-del-modelo")
    expect(page.get_by_role("heading", name="Acerca del modelo")).to_be_visible()
    expect(page.get_by_text("no está validado para mastografías")).to_be_visible()
    expect(page.get_by_text("Modelo de demostración sin entrenar")).to_be_visible()
    expect(page.get_by_text("fake-3c-1")).to_be_visible()
    # La ficha de prueba no trae métricas: la sección no aparece
    expect(page.get_by_role("heading", name="Métricas en el conjunto de prueba")).to_have_count(0)
    assert page.evaluate("document.documentElement.scrollWidth") <= 390
