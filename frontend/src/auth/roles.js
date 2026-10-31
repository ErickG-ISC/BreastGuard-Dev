// Pantalla inicial según el rol del usuario autenticado
export function homeFor(role) {
  if (role === 'platform_admin') return '/admin/tenants';
  if (role === 'patient') return '/paciente';
  if (role === 'tenant_admin') return '/institucion/usuarios';
  if (role === 'doctor') return '/medico';
  return '/';
}
