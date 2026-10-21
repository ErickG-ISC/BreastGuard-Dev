"""Consulta de catálogo compartida: qué exige el proyecto de toda tabla de `clinical`.

La usan la prueba de catálogo (sobre la base migrada) y la que demuestra que esa misma consulta
detecta una tabla sin RLS (sobre una tabla temporal dentro de una transacción con rollback).
"""

CLINICAL_TABLES_SQL = """
SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity,
       EXISTS (SELECT 1 FROM pg_attribute a WHERE a.attrelid = c.oid
               AND a.attname = 'tenant_id' AND a.attnotnull) AS has_tenant_id,
       (SELECT count(*) FROM pg_policy p WHERE p.polrelid = c.oid) AS policies,
       EXISTS (SELECT 1 FROM pg_policy p WHERE p.polrelid = c.oid
               AND p.polname = 'tenant_isolation' AND p.polpermissive
               AND p.polqual IS NOT NULL AND p.polwithcheck IS NOT NULL
               -- USING y WITH CHECK deben comparar tenant_id con el contexto: un
               -- WITH CHECK (true) no basta
               AND pg_get_expr(p.polqual, p.polrelid) LIKE '%tenant_id = %current_tenant_id()%'
               AND pg_get_expr(p.polwithcheck, p.polrelid)
                   LIKE '%tenant_id = %current_tenant_id()%') AS tenant_policy
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
    return problems
