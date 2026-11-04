"""CU-07: la paciente comparte un paquete cifrado (crear, listar, revocar, caducar y limpiar).

Lo que se comprueba además del flujo:
- en control solo hay el HMAC del código y metadatos: ningún dato clínico en sus columnas;
- en Storage el contenido es ilegible sin el código y solo se copian objetos propios;
- acceso cruzado: otra paciente (mismo tenant u otro) no ve, revoca ni usa análisis ajenos;
- la base impide crear o tocar paquetes desde sesiones que no son de la paciente.
"""

import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from backend.app.api.rate_limit import limiter
from backend.app.content.share_consent import current_share_consent
from backend.app.services import share_crypto
from tests.api.test_semana2_cruzado import create_analysis, submit_questionnaire
from tests.helpers import auth_headers, tenant_session

API = "/api/v1"
CRON = {"X-Cron-Secret": "s" * 40}


@pytest.fixture(autouse=True)
def cron_secret(monkeypatch):
    monkeypatch.setenv("REMINDER_CRON_SECRET", CRON["X-Cron-Secret"])


@pytest.fixture
def world(tenant_factory, user_factory, b2c_tenant):
    clinic = tenant_factory("clinica-a")
    return {
        "maria": user_factory(b2c_tenant, role="patient"),
        "ana": user_factory(b2c_tenant, role="patient"),
        "clinic_patient": user_factory(clinic, role="patient"),
        "doctor": user_factory(clinic, role="doctor", email="dra.ruiz@example.com"),
        "admin": user_factory(clinic, role="tenant_admin"),
    }


def body(**extra) -> dict:
    return {
        "consent_accepted": True,
        "consent_version": current_share_consent().version,
        **extra,
    }


def share(client, user, **extra):
    return client.post(f"{API}/shares", json=body(**extra), headers=auth_headers(user))


def control_rows(owner_engine, table: str) -> list:
    with owner_engine.connect() as conn:
        return conn.execute(text(f"SELECT * FROM control.{table}")).mappings().all()


def objects_under(storage, prefix: str) -> dict[str, bytes]:
    return {k: v for k, v in storage.objects.items() if k.startswith(prefix)}


class TestCrear:
    def test_paquete_completo_cifrado_y_solo_hash_en_control(
        self, client, storage, owner_engine, world
    ):
        maria = world["maria"]
        analysis = create_analysis(client, maria)
        submit_questionnaire(client, maria, age=41)
        client.post(
            f"{API}/symptoms",
            json={
                "entry_date": datetime.now(UTC).date().isoformat(),
                "side": "izquierdo",
                "zone": "axila",
                "symptoms": ["dolor"],
                "intensity": 4,
                "note": "nota privada de maria",
            },
            headers=auth_headers(maria),
        )

        response = share(
            client,
            maria,
            analysis_ids=[analysis["id"]],
            include_diary=True,
            include_questionnaire=True,
            include_identity=True,
        )
        assert response.status_code == 201, response.text
        assert response.headers["cache-control"] == "no-store"
        created = response.json()
        code = created["code"]
        assert len(code.replace("-", "")) == 26
        assert created["link"].endswith(f"/importar#c={code}")

        (row,) = control_rows(owner_engine, "share_packages")
        secret = share_crypto.from_code(code)
        assert row["key_hash"] == secret.lookup_hash
        assert code not in json.dumps({k: str(v) for k, v in row.items()})
        assert row["sections"] == {
            "analyses": True,
            "diary": True,
            "questionnaire": True,
            "notes": False,
            "identity": True,
        }
        assert row["consent_version"] == current_share_consent().version
        assert row["consent_sha256"] == current_share_consent().sha256

        # Storage: imagen, heatmap y contenido, todo cifrado bajo transfer/{uuid}/
        prefix = row["object_prefix"]
        package_id = row["id"]
        stored = objects_under(storage, prefix)
        assert len(stored) == 3 and f"{prefix}payload.bin" in stored
        originals = [v for k, v in storage.objects.items() if not k.startswith("transfer/")]
        for blob in stored.values():
            assert all(original not in blob for original in originals)
        payload = json.loads(
            share_crypto.decrypt(
                secret.key, package_id, "payload.bin", stored[f"{prefix}payload.bin"]
            )
        )
        assert payload["patient"]["age_years"] == 41
        assert payload["questionnaire"]["answers"]["age"] == 41
        (entry,) = payload["symptoms"]
        assert entry["note"] is None  # las notas solo van si se piden
        (item,) = payload["analyses"]
        image = share_crypto.decrypt(
            secret.key, package_id, item["image"], stored[prefix + item["image"]]
        )
        assert image in originals
        # Sin la llave correcta no se descifra
        with pytest.raises(share_crypto.DecryptionError):
            share_crypto.decrypt(
                share_crypto.new_secret().key,
                package_id,
                "payload.bin",
                stored[f"{prefix}payload.bin"],
            )

        with owner_engine.connect() as conn:
            actions = list(
                conn.scalars(
                    text(
                        "SELECT action FROM clinical.audit_log WHERE actor_id = :u "
                        "AND resource_type = 'share'"
                    ),
                    {"u": maria.id},
                )
            )
        assert actions == ["share.create"]

    def test_control_no_guarda_datos_clinicos(self, client, owner_engine, world):
        maria = world["maria"]
        analysis = create_analysis(client, maria)
        share(client, maria, analysis_ids=[analysis["id"]], include_diary=True)
        clinical_values = {
            analysis["predicted_class"],
            json.dumps(analysis["probabilities"]),
            "axila",
        }
        for table in ("share_packages", "share_events", "inbox_notices"):
            for row in control_rows(owner_engine, table):
                dumped = json.dumps({k: str(v) for k, v in row.items()})
                assert not any(value in dumped for value in clinical_values), table

    def test_notas_solo_si_se_piden(self, client, storage, owner_engine, world):
        maria = world["maria"]
        client.post(
            f"{API}/symptoms",
            json={
                "entry_date": datetime.now(UTC).date().isoformat(),
                "side": "derecho",
                "zone": "axila",
                "symptoms": ["dolor"],
                "intensity": 2,
                "note": "texto libre",
            },
            headers=auth_headers(maria),
        )
        code = share(client, maria, include_diary=True, include_notes=True).json()["code"]
        (row,) = control_rows(owner_engine, "share_packages")
        secret = share_crypto.from_code(code)
        blob = storage.objects[row["object_prefix"] + "payload.bin"]
        payload = json.loads(share_crypto.decrypt(secret.key, row["id"], "payload.bin", blob))
        assert payload["symptoms"][0]["note"] == "texto libre"

    @pytest.mark.parametrize(
        "extra",
        [
            {},  # nada que compartir
            {"include_notes": True},  # notas sin diario
            {"include_diary": True, "consent_accepted": False},
            {"include_diary": True, "expires_in_hours": 200},
            {"include_diary": True, "tenant_id": str(uuid.uuid4())},
        ],
    )
    def test_entrada_invalida_422(self, client, world, extra):
        response = client.post(
            f"{API}/shares", json={**body(), **extra}, headers=auth_headers(world["maria"])
        )
        assert response.status_code == 422

    def test_consentimiento_desactualizado_409(self, client, world):
        response = share(client, world["maria"], include_diary=True, consent_version="viejo")
        assert response.status_code == 409

    def test_fallo_de_storage_no_deja_nada(self, client, storage, owner_engine, world):
        maria = world["maria"]
        analysis = create_analysis(client, maria)
        storage.fail_on = "payload.bin"
        response = share(client, maria, analysis_ids=[analysis["id"]])
        assert response.status_code == 502
        assert objects_under(storage, "transfer/") == {}
        assert control_rows(owner_engine, "share_packages") == []

    def test_limite_de_paquetes_activos(self, client, world):
        for _ in range(5):
            assert share(client, world["maria"], include_diary=True).status_code == 201
        limiter.reset()  # aislar el límite de paquetes activos del de peticiones por minuto
        assert share(client, world["maria"], include_diary=True).status_code == 409

    def test_limite_de_peticiones(self, client, world):
        codes = [share(client, world["maria"], include_diary=True).status_code for _ in range(6)]
        assert codes[-1] == 429


class TestAccesoCruzado:
    @pytest.mark.parametrize("victim", ["ana", "clinic_patient"])
    def test_no_comparte_analisis_ajenos(self, client, storage, owner_engine, world, victim):
        theirs = create_analysis(client, world[victim])
        response = share(client, world["maria"], analysis_ids=[theirs["id"]])
        missing = share(client, world["maria"], analysis_ids=[str(uuid.uuid4())])
        assert response.status_code == missing.status_code == 422
        assert response.json() == missing.json()
        assert objects_under(storage, "transfer/") == {}
        assert control_rows(owner_engine, "share_packages") == []

    @pytest.mark.parametrize("intruder", ["ana", "clinic_patient"])
    def test_otra_paciente_no_ve_ni_revoca(self, client, owner_engine, world, intruder):
        package_id = share(client, world["maria"], include_diary=True).json()["id"]
        listed = client.get(f"{API}/shares", headers=auth_headers(world[intruder]))
        assert listed.json()["items"] == []
        revoked = client.delete(f"{API}/shares/{package_id}", headers=auth_headers(world[intruder]))
        missing = client.delete(
            f"{API}/shares/{uuid.uuid4()}", headers=auth_headers(world[intruder])
        )
        assert revoked.status_code == missing.status_code == 404
        (row,) = control_rows(owner_engine, "share_packages")
        assert row["status"] == "activo"

    @pytest.mark.parametrize("role", ["doctor", "admin"])
    def test_el_personal_no_usa_las_rutas_de_paciente(self, client, world, role):
        headers = auth_headers(world[role])
        assert client.post(f"{API}/shares", json=body(), headers=headers).status_code == 403
        assert client.get(f"{API}/shares", headers=headers).status_code == 403


class TestDestinataria:
    def test_doctora_activa_recibe_aviso_discreto(self, client, owner_engine, outbox, world):
        response = share(
            client, world["maria"], include_diary=True, recipient_email="Dra.Ruiz@example.com"
        )
        assert response.status_code == 201
        (row,) = control_rows(owner_engine, "share_packages")
        assert row["recipient_email"] == "dra.ruiz@example.com"
        assert row["recipient_user_id"] == world["doctor"].id
        (notice,) = control_rows(owner_engine, "inbox_notices")
        assert notice["user_id"] == world["doctor"].id and notice["kind"] == "share_received"
        (message,) = outbox.messages
        assert message.to == "dra.ruiz@example.com"
        for word in ("mama", "análisis", "paciente", world["maria"].email):
            assert word not in message.body.lower() and word not in message.subject.lower()

    @pytest.mark.parametrize("who", ["nadie", "clinic_patient", "admin"])
    def test_misma_respuesta_si_no_es_doctora(self, client, owner_engine, outbox, world, who):
        # Sin cuenta, paciente o administración: nada distinto para quien comparte
        email = "nadie@example.com" if who == "nadie" else world[who].email
        response = share(client, world["maria"], include_diary=True, recipient_email=email)
        assert response.status_code == 201
        assert set(response.json()) == {"id", "code", "link", "expires_at"}
        (row,) = control_rows(owner_engine, "share_packages")
        assert row["recipient_user_id"] is None
        assert control_rows(owner_engine, "inbox_notices") == []
        assert outbox.messages == []


class TestRevocarYCaducar:
    def test_revocar_borra_el_contenido(self, client, storage, owner_engine, world):
        maria = world["maria"]
        analysis = create_analysis(client, maria)
        package_id = share(client, maria, analysis_ids=[analysis["id"]]).json()["id"]
        response = client.delete(f"{API}/shares/{package_id}", headers=auth_headers(maria))
        assert response.status_code == 204
        (row,) = control_rows(owner_engine, "share_packages")
        assert row["status"] == "revocado" and row["objects_deleted_at"] is not None
        assert objects_under(storage, "transfer/") == {}
        again = client.delete(f"{API}/shares/{package_id}", headers=auth_headers(maria))
        assert again.status_code == 409
        (item,) = client.get(f"{API}/shares", headers=auth_headers(maria)).json()["items"]
        assert item["status"] == "revocado"
        assert [e["kind"] for e in item["events"]] == ["creado", "revocado"]

    def test_caducado_se_muestra_y_la_limpieza_lo_cierra(
        self, client, storage, owner_engine, world
    ):
        maria = world["maria"]
        package_id = share(client, maria, include_diary=True).json()["id"]
        with owner_engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE control.share_packages SET created_at = :c, expires_at = :e "
                    "WHERE id = :id"
                ),
                {
                    "c": datetime.now(UTC) - timedelta(days=2),
                    "e": datetime.now(UTC) - timedelta(minutes=1),
                    "id": package_id,
                },
            )
        (item,) = client.get(f"{API}/shares", headers=auth_headers(maria)).json()["items"]
        assert item["status"] == "caducado"
        assert (
            client.delete(f"{API}/shares/{package_id}", headers=auth_headers(maria)).status_code
            == 409
        )

        result = client.post(f"{API}/internal/shares/cleanup", headers=CRON)
        assert result.status_code == 200
        assert result.json() == {"expired": 1, "purged": 1, "failed": 0}
        (row,) = control_rows(owner_engine, "share_packages")
        assert row["status"] == "caducado" and row["objects_deleted_at"] is not None
        assert objects_under(storage, "transfer/") == {}
        # Idempotente
        again = client.post(f"{API}/internal/shares/cleanup", headers=CRON).json()
        assert again == {"expired": 0, "purged": 0, "failed": 0}

    def test_la_limpieza_reintenta_si_storage_falla(self, client, storage, owner_engine, world):
        maria = world["maria"]
        package_id = share(client, maria, include_diary=True).json()["id"]
        storage.fail_remove = True
        assert (
            client.delete(f"{API}/shares/{package_id}", headers=auth_headers(maria)).status_code
            == 204
        )
        assert client.post(f"{API}/internal/shares/cleanup", headers=CRON).json()["failed"] == 1
        storage.fail_remove = False
        assert client.post(f"{API}/internal/shares/cleanup", headers=CRON).json()["purged"] == 1

    def test_limpieza_sin_secreto(self, client):
        assert client.post(f"{API}/internal/shares/cleanup").status_code == 401


class TestDefensaEnLaBase:
    def _row(self, user, **extra) -> dict:
        return {
            "id": uuid.uuid4(),
            "t": user.tenant_id,
            "u": user.id,
            "h": "a" * 64,
            "p": f"transfer/{uuid.uuid4().hex}/",
            **extra,
        }

    INSERT = (
        "INSERT INTO control.share_packages (id, source_tenant_id, source_user_id, key_hash, "
        "expires_at, sections, analyses_count, size_bytes, consent_version, consent_sha256, "
        "consented_at, object_prefix) VALUES (:id, :t, :u, :h, now() + interval '1 day', "
        "'{}'::jsonb, 0, 0, 'v', 'x', now(), :p)"
    )

    @pytest.mark.parametrize("actor", ["doctor", "admin"])
    def test_sesiones_del_personal_no_crean_paquetes(self, world, actor):
        with (
            tenant_session(world[actor]) as session,
            pytest.raises(DBAPIError, match="Solo la paciente"),
        ):
            session.execute(text(self.INSERT), self._row(world["maria"]))

    def test_una_paciente_no_crea_paquetes_a_nombre_de_otra(self, world):
        with (
            tenant_session(world["maria"]) as session,
            pytest.raises(DBAPIError, match="es de quien lo crea"),
        ):
            session.execute(text(self.INSERT), self._row(world["ana"]))

    def test_la_paciente_no_marca_importado_ni_toca_paquetes_ajenos(
        self, client, owner_engine, world
    ):
        package_id = share(client, world["maria"], include_diary=True).json()["id"]
        attempts = [
            (world["maria"], "status = 'importado'"),
            (world["maria"], "claimed_by = source_user_id"),
            (world["ana"], "status = 'revocado'"),
        ]
        for user, change in attempts:
            with (
                tenant_session(user) as session,
                pytest.raises(DBAPIError, match="solo puede revocar sus paquetes"),
            ):
                session.execute(
                    text(f"UPDATE control.share_packages SET {change} WHERE id = :id"),
                    {"id": package_id},
                )
        (row,) = control_rows(owner_engine, "share_packages")
        assert row["status"] == "activo" and row["claimed_by"] is None


class TestCodigo:
    def test_formato_y_lectura_tolerante(self):
        secret = share_crypto.new_secret()
        assert [len(g) for g in secret.code.split("-")] == [5, 5, 5, 5, 6]
        messy = secret.code.lower().replace("-", " ").replace("0", "o").replace("1", "l")
        assert share_crypto.from_code(messy).lookup_hash == secret.lookup_hash

    @pytest.mark.parametrize("code", ["", "corto", "U" * 26, "Z" * 26, "!" * 26])
    def test_codigos_mal_formados(self, code):
        with pytest.raises(share_crypto.InvalidCode):
            share_crypto.from_code(code)

    def test_el_contenido_no_se_mueve_de_paquete_ni_de_nombre(self):
        secret = share_crypto.new_secret()
        package = uuid.uuid4()
        blob = share_crypto.encrypt(secret.key, package, "a.bin", b"datos")
        with pytest.raises(share_crypto.DecryptionError):
            share_crypto.decrypt(secret.key, uuid.uuid4(), "a.bin", blob)
        with pytest.raises(share_crypto.DecryptionError):
            share_crypto.decrypt(secret.key, package, "b.bin", blob)
        assert share_crypto.decrypt(secret.key, package, "a.bin", blob) == b"datos"


class TestDefensaDeEventosYAvisos:
    """Revisión de aislamiento: eventos, avisos y prefijos atados al paquete de quien escribe."""

    def _own_package(self, client, owner_engine, world, **extra) -> dict:
        share(client, world["maria"], include_diary=True, **extra)
        (row,) = control_rows(owner_engine, "share_packages")
        return row

    def test_otra_paciente_no_escribe_eventos_en_paquete_ajeno(self, client, owner_engine, world):
        row = self._own_package(client, owner_engine, world)
        with (
            tenant_session(world["ana"]) as session,
            pytest.raises(DBAPIError, match="Evento de paquete no permitido"),
        ):
            session.execute(
                text("INSERT INTO control.share_events (package_id, kind) VALUES (:p, 'revocado')"),
                {"p": row["id"]},
            )

    @pytest.mark.parametrize(
        ("kind", "names"),
        [("importado", False), ("creado", True)],
    )
    def test_la_paciente_no_inventa_importaciones_ni_nombres(
        self, client, owner_engine, world, kind, names
    ):
        row = self._own_package(client, owner_engine, world)
        with (
            tenant_session(world["maria"]) as session,
            pytest.raises(DBAPIError, match="Evento de paquete no permitido"),
        ):
            session.execute(
                text(
                    "INSERT INTO control.share_events (package_id, kind, doctor_name) "
                    "VALUES (:p, :k, :n)"
                ),
                {"p": row["id"], "k": kind, "n": "Dra. Falsa" if names else None},
            )

    def test_no_se_avisa_a_quien_no_es_la_destinataria(self, client, owner_engine, world):
        row = self._own_package(client, owner_engine, world)
        for user in (world["doctor"], world["admin"]):
            with (
                tenant_session(world["maria"]) as session,
                pytest.raises(DBAPIError, match="Aviso no permitido"),
            ):
                session.execute(
                    text(
                        "INSERT INTO control.inbox_notices (tenant_id, user_id, kind, ref_id) "
                        "VALUES (:t, :u, 'share_received', :p)"
                    ),
                    {"t": user.tenant_id, "u": user.id, "p": row["id"]},
                )

    def test_solo_la_destinataria_marca_su_aviso(self, client, owner_engine, world, outbox):
        self._own_package(client, owner_engine, world, recipient_email=world["doctor"].email)
        (notice,) = control_rows(owner_engine, "inbox_notices")
        sql = text("UPDATE control.inbox_notices SET read_at = now() WHERE id = :id")
        with (
            tenant_session(world["maria"]) as session,
            pytest.raises(DBAPIError, match="Solo la destinataria"),
        ):
            session.execute(sql, {"id": notice["id"]})
        with tenant_session(world["doctor"]) as session:
            assert session.execute(sql, {"id": notice["id"]}).rowcount == 1
            session.rollback()

    def test_el_prefijo_es_el_del_propio_paquete(self, client, owner_engine, world):
        row = self._own_package(client, owner_engine, world)
        other = dict(TestDefensaEnLaBase()._row(world["maria"]), p=row["object_prefix"])
        with (
            tenant_session(world["maria"]) as session,
            pytest.raises(DBAPIError, match="ck_share_packages_prefix|uq_share_packages_prefix"),
        ):
            session.execute(text(TestDefensaEnLaBase.INSERT), other)

    def test_la_paciente_no_oculta_un_paquete_activo_de_la_limpieza(
        self, client, owner_engine, world
    ):
        row = self._own_package(client, owner_engine, world)
        with (
            tenant_session(world["maria"]) as session,
            pytest.raises(DBAPIError, match="solo puede revocar"),
        ):
            session.execute(
                text("UPDATE control.share_packages SET objects_deleted_at = now() WHERE id = :id"),
                {"id": row["id"]},
            )

    def test_ningun_tenant_puede_llamarse_transfer(self, owner_engine):
        with (
            pytest.raises(DBAPIError, match="ck_tenants_slug_not_reserved"),
            owner_engine.begin() as conn,
        ):
            conn.execute(
                text(
                    "INSERT INTO control.tenants (slug, name, kind, plan) "
                    "VALUES ('transfer', 'x', 'institucion', 'basic')"
                )
            )
