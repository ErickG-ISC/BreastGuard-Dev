"""CU-08: la médica importa el paquete como COPIA en su tenant (ADR 0010).

- la copia aparece solo en el tenant de la doctora, con ella como responsable, y el original de
  la paciente no cambia;
- un solo uso: segundo uso, caducado, revocado, código incorrecto u otra destinataria dan el
  mismo 404; rol no doctor, 403;
- atómica: importaciones simultáneas, fallo a medias (no deja nada y se puede reintentar) y
  caída entre copiar y confirmar (no duplica);
- auditoría en ambos lados y evento `reasignado` cuando la ficha cambia de médica.
"""

import json
import threading
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from backend.app.api.rate_limit import limiter
from backend.app.db import new_session
from backend.app.services import share_crypto, share_import
from tests.api.test_semana2_cruzado import create_analysis, submit_questionnaire
from tests.api.test_shares import body, control_rows, objects_under
from tests.helpers import auth_headers, tenant_session

API = "/api/v1"


@pytest.fixture
def world(tenant_factory, user_factory, b2c_tenant):
    clinic, other = tenant_factory("clinica-a"), tenant_factory("clinica-b")
    return {
        "clinic": clinic,
        "other": other,
        "maria": user_factory(b2c_tenant, role="patient"),
        "doctor": user_factory(clinic, role="doctor"),
        "colleague": user_factory(clinic, role="doctor"),
        "admin": user_factory(clinic, role="tenant_admin"),
        "outsider": user_factory(other, role="doctor"),
    }


def shared(client, world, **extra) -> dict:
    maria = world["maria"]
    analysis = create_analysis(client, maria)
    submit_questionnaire(client, maria, age=44)
    exam = client.post(f"{API}/self-exams", headers=auth_headers(maria)).json()
    client.post(
        f"{API}/self-exams/{exam['id']}/finish",
        json={"noticed_change": "si", "note": "nota de la autoexploración"},
        headers=auth_headers(maria),
    )
    client.post(
        f"{API}/symptoms",
        json={
            "entry_date": datetime.now(UTC).date().isoformat(),
            "side": "izquierdo",
            "zone": "axila",
            "symptoms": ["dolor"],
            "intensity": 5,
            "self_exam_id": exam["id"],
        },
        headers=auth_headers(maria),
    )
    response = client.post(
        f"{API}/shares",
        json=body(
            analysis_ids=[analysis["id"]],
            include_diary=True,
            include_questionnaire=True,
            include_identity=True,
            **extra,
        ),
        headers=auth_headers(maria),
    )
    assert response.status_code == 201, response.text
    return {**response.json(), "analysis": analysis}


def do_import(client, doctor, code):
    return client.post(
        f"{API}/doctor/shares/import", json={"code": code}, headers=auth_headers(doctor)
    )


def clinic_rows(owner_engine, tenant_id, table) -> list:
    with owner_engine.connect() as conn:
        return (
            conn.execute(
                text(f"SELECT * FROM clinical.{table} WHERE tenant_id = :t"), {"t": tenant_id}
            )
            .mappings()
            .all()
        )


def package_row(owner_engine):
    (row,) = control_rows(owner_engine, "share_packages")
    return row


class TestImportar:
    def test_copia_completa_en_el_tenant_de_la_doctora(
        self, client, storage, owner_engine, world, b2c_tenant
    ):
        package = shared(client, world)
        originals = {k: v for k, v in storage.objects.items() if k.startswith("b2c/")}
        b2c_before = {
            t: len(clinic_rows(owner_engine, b2c_tenant.id, t))
            for t in ("patients", "analyses", "symptom_entries", "self_exams", "questionnaires")
        }

        response = do_import(client, world["doctor"], package["code"])
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["analyses"] == 1 and result["symptoms"] == 1
        assert result["already_imported"] is False

        clinic = world["clinic"].id
        (patient,) = clinic_rows(owner_engine, clinic, "patients")
        assert patient["id"] == uuid.UUID(result["patient_id"])
        assert patient["origin"] == "importado" and patient["user_id"] is None
        assert patient["responsible_doctor_id"] == world["doctor"].id
        assert patient["source_package_id"] == package_row(owner_engine)["id"]
        assert patient["age_years"] == 44
        (image,) = clinic_rows(owner_engine, clinic, "medical_images")
        (analysis,) = clinic_rows(owner_engine, clinic, "analyses")
        assert image["object_path"].startswith("clinica-a/images/")
        assert analysis["heatmap_path"].startswith("clinica-a/heatmaps/")
        assert analysis["predicted_class"] == package["analysis"]["predicted_class"]
        # Las imágenes copiadas son idénticas a las originales (descifradas)
        assert storage.objects[image["object_path"]] in originals.values()
        (exam,) = clinic_rows(owner_engine, clinic, "self_exams")
        (entry,) = clinic_rows(owner_engine, clinic, "symptom_entries")
        assert entry["self_exam_id"] == exam["id"] and entry["note"] is None
        assert exam["note"] is None  # las notas no se pidieron
        assert len(clinic_rows(owner_engine, clinic, "questionnaires")) == 1

        # El original de la paciente no cambia
        for table, count in b2c_before.items():
            assert len(clinic_rows(owner_engine, b2c_tenant.id, table)) == count, table
        assert all(storage.objects.get(k) == v for k, v in originals.items())

        # Control: importado, evento con nombres y contenido de transfer/ borrado
        row = package_row(owner_engine)
        assert row["status"] == "importado" and row["imported_tenant_id"] == clinic
        assert row["objects_deleted_at"] is not None
        assert objects_under(storage, "transfer/") == {}
        (item,) = client.get(f"{API}/shares", headers=auth_headers(world["maria"])).json()["items"]
        assert item["status"] == "importado"
        imported = item["events"][-1]
        assert imported["kind"] == "importado"
        assert imported["institution_name"] == "Tenant clinica-a"
        assert imported["doctor_name"] == "Usuario de prueba"

        # Auditoría en ambos lados
        with owner_engine.connect() as conn:
            actions = conn.execute(
                text(
                    "SELECT tenant_id, action FROM clinical.audit_log "
                    "WHERE action IN ('share.create', 'share.import')"
                )
            ).all()
        assert set(actions) == {(b2c_tenant.id, "share.create"), (clinic, "share.import")}

    def test_otra_doctora_y_otro_tenant_no_ven_la_copia(self, client, owner_engine, world):
        package = shared(client, world)
        do_import(client, world["doctor"], package["code"])
        for user in (world["colleague"], world["admin"], world["outsider"]):
            with tenant_session(user) as session:
                assert session.execute(text("SELECT count(*) FROM clinical.patients")).scalar() == 0
        with tenant_session(world["doctor"]) as session:
            assert session.execute(text("SELECT count(*) FROM clinical.patients")).scalar() == 1

    def test_notas_si_se_pidieron(self, client, owner_engine, world):
        package = shared(client, world, include_notes=True)
        do_import(client, world["doctor"], package["code"])
        (exam,) = clinic_rows(owner_engine, world["clinic"].id, "self_exams")
        assert exam["note"] == "nota de la autoexploración"


class TestUnSoloUso:
    def _same_404(self, client, doctor, code):
        response = do_import(client, doctor, code)
        random = do_import(client, doctor, share_crypto.new_secret().code)
        assert response.status_code == random.status_code == 404
        assert response.json() == random.json()

    def test_segundo_uso(self, client, world):
        package = shared(client, world)
        assert do_import(client, world["doctor"], package["code"]).status_code == 200
        self._same_404(client, world["colleague"], package["code"])
        self._same_404(client, world["doctor"], package["code"])

    def test_revocado(self, client, world):
        package = shared(client, world)
        client.delete(f"{API}/shares/{package['id']}", headers=auth_headers(world["maria"]))
        self._same_404(client, world["doctor"], package["code"])

    def test_caducado(self, client, owner_engine, world):
        package = shared(client, world)
        with owner_engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE control.share_packages SET created_at = now() - interval '2 days', "
                    "expires_at = now() - interval '1 minute'"
                )
            )
        self._same_404(client, world["doctor"], package["code"])

    @pytest.mark.parametrize("code", ["basura", "Z" * 26, ""])
    def test_codigos_mal_formados(self, client, world, code):
        response = do_import(client, world["doctor"], code)
        assert response.status_code in (404, 422)

    @pytest.mark.parametrize("role", ["maria", "admin"])
    def test_solo_doctoras(self, client, world, role):
        package = shared(client, world)
        assert do_import(client, world[role], package["code"]).status_code == 403


class TestDestinataria:
    def test_otra_doctora_no_usa_un_paquete_dirigido(self, client, owner_engine, world, outbox):
        package = shared(client, world, recipient_email=world["doctor"].email)
        response = do_import(client, world["colleague"], package["code"])
        random = do_import(client, world["colleague"], share_crypto.new_secret().code)
        assert response.status_code == 404 and response.json() == random.json()
        row = package_row(owner_engine)
        assert row["status"] == "activo" and row["failed_attempts"] == 1
        assert do_import(client, world["doctor"], package["code"]).status_code == 200

    def test_cinco_intentos_ajenos_revocan_el_paquete(self, client, owner_engine, world, outbox):
        package = shared(client, world, recipient_email=world["doctor"].email)
        for _ in range(5):
            limiter.reset()  # aislar el contador por paquete del de la cuenta
            do_import(client, world["colleague"], package["code"])
        assert package_row(owner_engine)["status"] == "revocado"
        limiter.reset()
        assert do_import(client, world["doctor"], package["code"]).status_code == 404

    def test_aviso_a_la_destinataria_y_leido_al_importar(self, client, world, outbox):
        package = shared(client, world, recipient_email=world["doctor"].email)
        headers = auth_headers(world["doctor"])
        (notice,) = client.get(f"{API}/doctor/notices", headers=headers).json()
        assert notice["kind"] == "share_received" and notice["read_at"] is None
        assert (
            client.get(f"{API}/doctor/notices", headers=auth_headers(world["colleague"])).json()
            == []
        )
        do_import(client, world["doctor"], package["code"])
        (notice,) = client.get(f"{API}/doctor/notices", headers=headers).json()
        assert notice["read_at"] is not None


class TestLimiteDeIntentos:
    def test_cinco_fallos_por_cuenta_dan_429(self, client, world):
        for _ in range(5):
            assert (
                do_import(client, world["doctor"], share_crypto.new_secret().code).status_code
                == 404
            )
        package = shared(client, world)
        # Ni siquiera un código válido pasa mientras dura el bloqueo
        assert do_import(client, world["doctor"], package["code"]).status_code == 429


class TestAtomicidad:
    def test_fallo_a_medias_no_deja_nada_y_se_puede_reintentar(
        self, client, storage, owner_engine, world
    ):
        package = shared(client, world)
        storage.fail_on = "clinica-a/heatmaps/"
        assert do_import(client, world["doctor"], package["code"]).status_code == 502
        assert clinic_rows(owner_engine, world["clinic"].id, "patients") == []
        assert objects_under(storage, "clinica-a/") == {}
        row = package_row(owner_engine)
        assert row["status"] == "activo" and row["claimed_by"] is None
        storage.fail_on = None
        assert do_import(client, world["doctor"], package["code"]).status_code == 200

    def test_caida_entre_copiar_y_confirmar_no_duplica(
        self, client, owner_engine, world, monkeypatch
    ):
        package = shared(client, world)
        real = share_import._confirm
        monkeypatch.setattr(
            share_import, "_confirm", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("caída"))
        )
        with pytest.raises(RuntimeError):
            do_import(client, world["doctor"], package["code"])
        monkeypatch.setattr(share_import, "_confirm", real)
        # Mientras el reclamo es reciente, el reintento espera
        assert do_import(client, world["doctor"], package["code"]).status_code == 409
        with owner_engine.begin() as conn:
            conn.execute(
                text("UPDATE control.share_packages SET claimed_at = now() - interval '11 minutes'")
            )
        retry = do_import(client, world["doctor"], package["code"])
        assert retry.status_code == 200 and retry.json()["already_imported"] is True
        assert len(clinic_rows(owner_engine, world["clinic"].id, "patients")) == 1
        assert package_row(owner_engine)["status"] == "importado"

    def test_reclamos_simultaneos_solo_gana_uno(self, client, world):
        package = shared(client, world)
        lookup = share_crypto.from_code(package["code"]).lookup_hash
        wins, barrier = [], threading.Barrier(2)

        class Auth:
            def __init__(self, user):
                self.user_id = user.id

        def claim(user):
            with new_session() as control:
                barrier.wait()
                wins.append(share_import._claim(control, Auth(user), lookup))

        threads = [
            threading.Thread(target=claim, args=(world[k],)) for k in ("doctor", "colleague")
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert sum(row is not None for row in wins) == 1


class TestReasignado:
    def test_el_traspaso_de_una_ficha_importada_avisa_a_la_paciente(self, client, world):
        package = shared(client, world)
        do_import(client, world["doctor"], package["code"])
        handover = client.post(
            f"{API}/institution/users/{world['doctor'].id}/handover",
            json={"to_user_id": str(world["colleague"].id)},
            headers=auth_headers(world["admin"]),
        ).json()
        accepted = client.post(
            f"{API}/doctor/handovers/{handover['id']}/accept",
            headers=auth_headers(world["colleague"]),
        )
        assert accepted.status_code == 200
        (item,) = client.get(f"{API}/shares", headers=auth_headers(world["maria"])).json()["items"]
        event = item["events"][-1]
        assert event["kind"] == "reasignado"
        assert event["institution_name"] == "Tenant clinica-a"

    def test_la_doctora_no_inventa_reasignaciones(self, client, owner_engine, world):
        package = shared(client, world)
        do_import(client, world["doctor"], package["code"])
        package_id = package_row(owner_engine)["id"]
        sql = text(
            "INSERT INTO control.share_events (package_id, kind, institution_name, doctor_name) "
            "VALUES (:p, 'reasignado', :i, :d)"
        )
        attempts = [
            (world["colleague"], "Tenant clinica-a", "Usuario de prueba"),  # no es su ficha
            (world["outsider"], "Tenant clinica-b", "Usuario de prueba"),  # otro tenant
            (world["doctor"], "Otra institución", "Usuario de prueba"),  # nombres falsos
        ]
        for user, institution, doctor in attempts:
            with (
                tenant_session(user) as session,
                pytest.raises(DBAPIError, match="Evento de paquete no permitido"),
            ):
                session.execute(sql, {"p": package_id, "i": institution, "d": doctor})


class TestTraspasoEndurecido:
    """Respuesta 2 del inventario: nadie se traspasa pacientes a sí misma."""

    def test_la_admin_no_puede_ser_destino(self, client, world):
        response = client.post(
            f"{API}/institution/users/{world['doctor'].id}/handover",
            json={"to_user_id": str(world["admin"].id)},
            headers=auth_headers(world["admin"]),
        )
        assert response.status_code == 422

    def test_platform_admin_no_puede_ser_destino(self, client, world, user_factory):
        platform = user_factory(role="platform_admin")
        response = client.post(
            f"{API}/admin/users/{world['doctor'].id}/handover",
            json={"to_user_id": str(platform.id)},
            headers=auth_headers(platform),
        )
        assert response.status_code == 404

    def test_no_se_cambia_su_propio_rol_para_recibir(self, client, world):
        response = client.patch(
            f"{API}/institution/users/{world['admin'].id}",
            json={"role": "doctor"},
            headers=auth_headers(world["admin"]),
        )
        assert response.status_code == 422

    def test_crear_un_traspaso_avisa_a_origen_y_demas_admins(
        self, client, world, user_factory, outbox
    ):
        second_admin = user_factory(world["clinic"], role="tenant_admin")
        client.post(
            f"{API}/institution/users/{world['doctor'].id}/handover",
            json={"to_user_id": str(world["colleague"].id)},
            headers=auth_headers(world["admin"]),
        )
        recipients = {m.to for m in outbox.messages}
        assert recipients == {world["doctor"].email, second_admin.email}
        for message in outbox.messages:
            assert "paciente" in message.body.lower()  # el tema administrativo, sin nombres
            assert world["colleague"].email not in message.body


class TestContenidoNoConfiable:
    """Revisión de aislamiento: el contenido descifrado se valida antes de copiar nada."""

    def _tamper(self, storage, owner_engine, code, change):
        row = package_row(owner_engine)
        secret = share_crypto.from_code(code)
        name = row["object_prefix"] + "payload.bin"
        payload = json.loads(
            share_crypto.decrypt(secret.key, row["id"], "payload.bin", storage.objects[name])
        )
        change(payload)
        storage.objects[name] = share_crypto.encrypt(
            secret.key, row["id"], "payload.bin", json.dumps(payload).encode()
        )

    def _rejected(self, client, storage, owner_engine, world, package):
        response = do_import(client, world["doctor"], package["code"])
        assert response.status_code == 502
        assert clinic_rows(owner_engine, world["clinic"].id, "patients") == []
        assert objects_under(storage, "clinica-a/") == {}
        row = package_row(owner_engine)
        assert row["status"] == "activo" and row["claimed_by"] is None

    @pytest.mark.parametrize(
        "change",
        [
            lambda p: p["analyses"][0].update(image="../otro/x.bin"),
            lambda p: p["analyses"][0].update(heatmap="b2c/images/x.png"),
            lambda p: p.update(patient="no es un objeto"),
            lambda p: p.update(analyses=["no es un objeto"]),
            lambda p: p.update(extra="campo desconocido"),
            lambda p: p["analyses"][0].update(predicted_class="inventada"),
            lambda p: p["symptoms"][0].update(note="x" * 5000),
            # Más análisis de los que la paciente declaró al compartir
            lambda p: p["analyses"].append(dict(p["analyses"][0])),
        ],
        ids=[
            "ruta_relativa",
            "ruta_de_tenant",
            "paciente_mal_formada",
            "analisis_mal_formado",
            "campo_extra",
            "clase_inventada",
            "nota_enorme",
            "mas_analisis_de_los_declarados",
        ],
    )
    def test_contenido_alterado_se_rechaza_sin_dejar_nada(
        self, client, storage, owner_engine, world, change
    ):
        package = shared(client, world)
        self._tamper(storage, owner_engine, package["code"], change)
        self._rejected(client, storage, owner_engine, world, package)

    def test_la_limpieza_no_caduca_una_importacion_en_curso(
        self, client, owner_engine, world, monkeypatch
    ):
        monkeypatch.setenv("REMINDER_CRON_SECRET", "s" * 40)
        package = shared(client, world)
        lookup = share_crypto.from_code(package["code"]).lookup_hash

        class Auth:
            user_id = world["doctor"].id

        with new_session() as control:
            assert share_import._claim(control, Auth(), lookup) is not None
        with owner_engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE control.share_packages SET created_at = now() - interval '2 days', "
                    "expires_at = now() - interval '1 minute'"
                )
            )
        result = client.post(f"{API}/internal/shares/cleanup", headers={"X-Cron-Secret": "s" * 40})
        assert result.json()["expired"] == 0
        assert package_row(owner_engine)["status"] == "importando"

    def test_no_confirma_si_perdio_el_reclamo(self, client, owner_engine, world, monkeypatch):
        package = shared(client, world)
        real_copy = share_import._copy

        def copy_then_lose_claim(*args, **kwargs):
            result = real_copy(*args, **kwargs)
            with owner_engine.begin() as conn:
                conn.execute(text("UPDATE control.share_packages SET status = 'caducado'"))
            return result

        monkeypatch.setattr(share_import, "_copy", copy_then_lose_claim)
        response = do_import(client, world["doctor"], package["code"])
        assert response.status_code == 409
        assert package_row(owner_engine)["status"] == "caducado"


class TestCampanaDeLaPaciente:
    def test_importar_y_reasignar_avisan_a_la_paciente(
        self, client, world, b2c_tenant, user_factory
    ):
        package = shared(client, world)
        headers = auth_headers(world["maria"])
        do_import(client, world["doctor"], package["code"])
        (notice,) = client.get(f"{API}/notices", params={"unread": True}, headers=headers).json()
        assert notice["kind"] == "share_update"

        # Otra paciente no puede marcarlo; ella sí
        ana = user_factory(b2c_tenant, role="patient")
        url = f"{API}/notices/{notice['id']}/read"
        assert client.post(url, headers=auth_headers(ana)).status_code == 404
        assert client.post(url, headers=headers).status_code == 204
        assert client.get(f"{API}/notices", params={"unread": True}, headers=headers).json() == []

        handover = client.post(
            f"{API}/institution/users/{world['doctor'].id}/handover",
            json={"to_user_id": str(world["colleague"].id)},
            headers=auth_headers(world["admin"]),
        ).json()
        client.post(
            f"{API}/doctor/handovers/{handover['id']}/accept",
            headers=auth_headers(world["colleague"]),
        )
        (again,) = client.get(f"{API}/notices", params={"unread": True}, headers=headers).json()
        assert again["kind"] == "share_update"

    def test_la_doctora_no_avisa_por_paquetes_ajenos(self, client, owner_engine, world):
        package = shared(client, world)
        do_import(client, world["doctor"], package["code"])
        row = package_row(owner_engine)
        sql = text(
            "INSERT INTO control.inbox_notices (tenant_id, user_id, kind, ref_id) "
            "VALUES (:t, :u, 'share_update', :p)"
        )
        params = {"t": world["maria"].tenant_id, "u": world["maria"].id, "p": row["id"]}
        for doctor in (world["colleague"], world["outsider"]):
            with (
                tenant_session(doctor) as session,
                pytest.raises(DBAPIError, match="Aviso no permitido"),
            ):
                session.execute(sql, params)
        # Ni la responsable puede avisar a otra persona que no sea la paciente de origen
        with (
            tenant_session(world["doctor"]) as session,
            pytest.raises(DBAPIError, match="Aviso no permitido"),
        ):
            session.execute(sql, {**params, "u": world["admin"].id, "t": world["clinic"].id})
