"""Desactiva y purga un tenant por slug: borra sus filas clínicas, sus usuarios y su fila.

Demostración de separación: como todo dato clínico lleva tenant_id, purgar un tenant es borrar
sus filas sin tocar las de nadie más. Usa el rol DUEÑO (DATABASE_URL) porque la app no tiene
DELETE en audit_log ni en control; nunca lo hace la app en ejecución.

La interfaz de administración solo SOLICITA la purga (desactiva y marca el tenant, ADR 0008);
este script la ejecuta. La bitácora de plataforma (control.admin_events) se conserva y recibe un
evento `tenant.purge`.

Uso, desde la raíz del repo:
    python -m backend.scripts.purge_tenant --pending              (purgas solicitadas en la UI)
    python -m backend.scripts.purge_tenant --slug clinica-x --dry-run
    python -m backend.scripts.purge_tenant --slug clinica-x       (pide escribir el slug)
"""

import argparse
import sys
from dataclasses import dataclass, field

from dotenv import load_dotenv
from sqlalchemy import Connection, Engine, create_engine, text
from sqlalchemy.engine import make_url

# Orden de borrado (hijas antes que padres). Si aparece una tabla clínica nueva, la purga se
# detiene hasta que se agregue aquí: así nunca deja filas huérfanas de un tenant.
CLINICAL_DELETE_ORDER = (
    "audit_log",
    "questionnaires",
    "analyses",
    "symptom_entries",
    "self_exams",
    "medical_images",
    "patients",
)


class PurgeError(Exception):
    pass


@dataclass
class PurgeSummary:
    slug: str
    deleted: dict[str, int] = field(default_factory=dict)
    dry_run: bool = False


def _require_bypass(conn: Connection) -> None:
    row = conn.execute(
        text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")
    ).one()
    if not (row.rolsuper or row.rolbypassrls):
        raise PurgeError("La purga requiere el rol dueño con BYPASSRLS (DATABASE_URL)")


def pending_slugs(engine: Engine) -> list[str]:
    """Tenants con purga solicitada desde la interfaz, del más antiguo al más reciente."""
    with engine.connect() as conn:
        return list(
            conn.scalars(
                text(
                    "SELECT slug FROM control.tenants WHERE purge_requested_at IS NOT NULL "
                    "ORDER BY purge_requested_at"
                )
            )
        )


def purge_tenant(
    engine: Engine,
    slug: str,
    *,
    dry_run: bool = False,
    allow_b2c: bool = False,
    require_request: bool = False,
) -> PurgeSummary:
    summary = PurgeSummary(slug=slug, dry_run=dry_run)
    with engine.connect() as conn:
        transaction = conn.begin()
        try:
            _require_bypass(conn)
            tenant = conn.execute(
                text(
                    "SELECT id, kind, purge_requested_at FROM control.tenants "
                    "WHERE slug = :slug FOR UPDATE"
                ),
                {"slug": slug},
            ).first()
            if tenant is None:
                raise PurgeError(f"No existe el tenant {slug!r}")
            if tenant.kind == "b2c" and not allow_b2c:
                raise PurgeError("El tenant b2c solo se purga con --allow-b2c")
            if require_request and tenant.purge_requested_at is None:
                raise PurgeError(f"La purga de {slug!r} ya no está solicitada (¿se canceló?)")

            tables = set(
                conn.scalars(
                    text(
                        "SELECT c.relname FROM pg_class c "
                        "JOIN pg_namespace n ON n.oid = c.relnamespace "
                        "WHERE n.nspname = 'clinical' AND c.relkind IN ('r', 'p')"
                    )
                )
            )
            if tables != set(CLINICAL_DELETE_ORDER):
                raise PurgeError("Hay tablas clínicas no contempladas en la purga; actualízala")

            conn.execute(
                text("UPDATE control.tenants SET is_active = false WHERE id = :id"),
                {"id": tenant.id},
            )
            for table in CLINICAL_DELETE_ORDER:
                result = conn.execute(
                    text(f"DELETE FROM clinical.{table} WHERE tenant_id = :id"), {"id": tenant.id}
                )
                summary.deleted[f"clinical.{table}"] = result.rowcount
            # Datos de cuenta ligados a los usuarios del tenant, antes de borrar los usuarios
            result = conn.execute(
                text("DELETE FROM control.invitations WHERE tenant_id = :id"), {"id": tenant.id}
            )
            summary.deleted["control.invitations"] = result.rowcount
            for table in ("reminder_notices", "reminders", "consents", "subscriptions"):
                result = conn.execute(
                    text(
                        f"DELETE FROM control.{table} WHERE user_id IN "
                        "(SELECT id FROM control.users WHERE tenant_id = :id)"
                    ),
                    {"id": tenant.id},
                )
                summary.deleted[f"control.{table}"] = result.rowcount
            for table, column in (("users", "tenant_id"), ("tenants", "id")):
                result = conn.execute(
                    text(f"DELETE FROM control.{table} WHERE {column} = :id"), {"id": tenant.id}
                )
                summary.deleted[f"control.{table}"] = result.rowcount
            # La bitácora de plataforma se conserva (sin FK al tenant) y registra la purga
            conn.execute(
                text(
                    "INSERT INTO control.admin_events (actor_role, action, tenant_id, "
                    "target_type, target_id) VALUES ('system', 'tenant.purge', :id, 'tenant', :id)"
                ),
                {"id": tenant.id},
            )
        except Exception:
            transaction.rollback()
            raise
        if dry_run:
            transaction.rollback()
        else:
            transaction.commit()
    return summary


def _purge_files(slug: str) -> int:
    from backend.app.services.storage import SupabaseStorage

    try:
        removed = SupabaseStorage().remove_prefix(f"{slug}/")
    except Exception as exc:
        print(
            f"La base quedó purgada, pero falló Storage ({type(exc).__name__}). "
            f"Quedan objetos bajo {slug}/: bórralos desde Supabase > Storage.",
            file=sys.stderr,
        )
        return 2
    print(f"Borrados {removed} objetos de Storage bajo {slug}/")
    return 0


def main() -> int:
    load_dotenv()
    import os

    parser = argparse.ArgumentParser(description="Desactiva y purga un tenant por slug")
    target_group = parser.add_mutually_exclusive_group(required=True)
    target_group.add_argument("--slug")
    target_group.add_argument(
        "--pending", action="store_true", help="Purga los tenants solicitados desde la UI"
    )
    parser.add_argument("--dry-run", action="store_true", help="Cuenta sin borrar nada")
    parser.add_argument("--allow-b2c", action="store_true")
    parser.add_argument("--keep-files", action="store_true", help="No borra objetos de Storage")
    args = parser.parse_args()

    target = make_url(os.environ["DATABASE_URL"])
    print(f"Base de destino: {target.host}:{target.port}/{target.database}")
    engine = create_engine(os.environ["DATABASE_URL"])
    status = 0
    try:
        slugs = pending_slugs(engine) if args.pending else [args.slug]
        if not slugs:
            print("No hay purgas solicitadas.")
        for slug in slugs:
            if not args.dry_run:
                typed = input(
                    f"Esto borra TODOS los datos de {slug!r}. Escribe el slug para confirmar: "
                )
                if typed.strip() != slug:
                    print(f"Confirmación incorrecta; {slug!r} no se borró.", file=sys.stderr)
                    status = 1
                    continue
            try:
                summary = purge_tenant(
                    engine,
                    slug,
                    dry_run=args.dry_run,
                    allow_b2c=args.allow_b2c,
                    require_request=args.pending,
                )
            except PurgeError as exc:
                print(str(exc), file=sys.stderr)
                status = 1
                continue
            verb = "Se borrarían" if args.dry_run else "Borradas"
            for table, count in summary.deleted.items():
                print(f"{verb} {count} filas de {table}")
            if not args.dry_run and not args.keep_files:
                status = max(status, _purge_files(slug))
    finally:
        engine.dispose()
    return status


if __name__ == "__main__":
    sys.exit(main())
