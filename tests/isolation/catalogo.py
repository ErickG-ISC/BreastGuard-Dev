"""Consulta de catálogo compartida: qué exige el proyecto de toda tabla de `clinical`.

La usan la prueba de catálogo (sobre la base migrada) y la que demuestra que esa misma consulta
detecta una tabla sin RLS (sobre una tabla temporal dentro de una transacción con rollback).
"""

# Texto de la política de aislamiento sin espacios, tal como lo devuelve pg_get_expr
EXPECTED_TENANT_POLICY = "(tenant_id=(SELECTclinical.current_tenant_id()AScurrent_tenant_id))"

CLINICAL_TABLES_SQL = f"""
SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity,
       EXISTS (SELECT 1 FROM pg_attribute a WHERE a.attrelid = c.oid
               AND a.attname = 'tenant_id' AND a.attnotnull) AS has_tenant_id,
       (SELECT count(*) FROM pg_policy p WHERE p.polrelid = c.oid) AS policies,
       EXISTS (SELECT 1 FROM pg_policy p WHERE p.polrelid = c.oid
               AND p.polname = 'tenant_isolation' AND p.polpermissive
               AND p.polqual IS NOT NULL AND p.polwithcheck IS NOT NULL
               -- USING y WITH CHECK deben ser EXACTAMENTE la comparación con el contexto:
               -- ni WITH CHECK (true) ni "... OR true" pasan
               AND regexp_replace(pg_get_expr(p.polqual, p.polrelid), '\\s', '', 'g')
                   = '{EXPECTED_TENANT_POLICY}'
               AND regexp_replace(pg_get_expr(p.polwithcheck, p.polrelid), '\\s', '', 'g')
                   = '{EXPECTED_TENANT_POLICY}') AS tenant_policy,
       -- tenant_isolation solo separa tenants; el acceso por rol lo da una RESTRICTIVE (ALL o
       -- por comando) para leer (USING) y otra para insertar (WITH CHECK)
       EXISTS (SELECT 1 FROM pg_policy p WHERE p.polrelid = c.oid AND NOT p.polpermissive
               AND p.polcmd IN ('*', 'r') AND p.polqual IS NOT NULL) AS role_read_policy,
       EXISTS (SELECT 1 FROM pg_policy p WHERE p.polrelid = c.oid AND NOT p.polpermissive
               AND p.polcmd IN ('*', 'a') AND p.polwithcheck IS NOT NULL) AS role_insert_policy
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'clinical' AND c.relkind IN ('r', 'p')
"""


def rls_problems(tables) -> list[str]:
    """Mensajes de incumplimiento (lista vacía = todas las tablas cumplen)."""
    problems: list[str] = []
    for t in tables:
        if not t.has_tenant_id:
            problems.append(f"clinical.{t.relname} sin tenant_id NOT NULL")
        if not t.relrowsecurity:
            problems.append(f"clinical.{t.relname} sin RLS habilitado")
        if not t.relforcerowsecurity:
            problems.append(f"clinical.{t.relname} sin RLS forzado")
        if t.policies < 1:
            problems.append(f"clinical.{t.relname} sin políticas")
        if not t.tenant_policy:
            problems.append(f"clinical.{t.relname} sin tenant_isolation con USING y WITH CHECK")
        if not (t.role_read_policy and t.role_insert_policy):
            problems.append(f"clinical.{t.relname} sin política RESTRICTIVE por rol")
    return problems
