"""Desactiva y purga un tenant por slug: borra sus filas clínicas, sus usuarios y su fila.

Demostración de separación: como todo dato clínico lleva tenant_id, purgar un tenant es borrar
sus filas sin tocar las de nadie más. Usa el rol DUEÑO (DATABASE_URL) porque la app no tiene
DELETE en audit_log ni en control; nunca lo hace la app en ejecución.

Uso, desde la raíz del repo:
    python -m backend.scripts.purge_tenant --slug clinica-x --dry-run
    python -m backend.scripts.purge_tenant --slug clinica-x      (pide escribir el slug)
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


def purge_tenant(
    engine: Engine, slug: str, *, dry_run: bool = False, allow_b2c: bool = False
) -> PurgeSummary:
    summary = PurgeSummary(slug=slug, dry_run=dry_run)
    with engine.connect() as conn:
        transaction = conn.begin()
        try:
            _require_bypass(conn)
            tenant = conn.execute(
                text("SELECT id, kind FROM control.tenants WHERE slug = :slug"), {"slug": slug}
            ).first()
            if tenant is None:
                raise PurgeError(f"No existe el tenant {slug!r}")
            if tenant.kind == "b2c" and not allow_b2c:
                raise PurgeError("El tenant b2c solo se purga con --allow-b2c")

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
        except Exception:
            transaction.rollback()
            raise
        if dry_run:
            transaction.rollback()
        else:
            transaction.commit()
    return summary


def main() -> int:
    load_dotenv()
    import os

    parser = argparse.ArgumentParser(description="Desactiva y purga un tenant por slug")
    parser.add_argument("--slug", required=True)
    parser.add_argument("--dry-run", action="store_true", help="Cuenta sin borrar nada")
    parser.add_argument("--allow-b2c", action="store_true")
    parser.add_argument("--keep-files", action="store_true", help="No borra objetos de Storage")
    args = parser.parse_args()

    target = make_url(os.environ["DATABASE_URL"])
    print(f"Base de destino: {target.host}:{target.port}/{target.database}")
    if not args.dry_run:
        typed = input(
            f"Esto borra TODOS los datos de {args.slug!r}. Escribe el slug para confirmar: "
        )
        if typed.strip() != args.slug:
            print("Confirmación incorrecta; no se borró nada.", file=sys.stderr)
            return 1

    engine = create_engine(os.environ["DATABASE_URL"])
    try:
        summary = purge_tenant(engine, args.slug, dry_run=args.dry_run, allow_b2c=args.allow_b2c)
    except PurgeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    finally:
        engine.dispose()

    verb = "Se borrarían" if args.dry_run else "Borradas"
    for table, count in summary.deleted.items():
        print(f"{verb} {count} filas de {table}")
    if not args.dry_run and not args.keep_files:
        from backend.app.services.storage import SupabaseStorage

        try:
            removed = SupabaseStorage().remove_prefix(f"{args.slug}/")
        except Exception as exc:
            print(
                f"La base quedó purgada, pero falló Storage ({type(exc).__name__}). "
                f"Quedan objetos bajo {args.slug}/: bórralos desde Supabase > Storage.",
                file=sys.stderr,
            )
            return 2
        print(f"Borrados {removed} objetos de Storage bajo {args.slug}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
