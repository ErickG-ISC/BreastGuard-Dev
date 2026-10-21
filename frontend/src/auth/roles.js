// Pantalla inicial según el rol del usuario autenticado
export function homeFor(role) {
  if (role === 'platform_admin') return '/admin/tenants';
  if (role === 'patient') return '/paciente';
  return '/';
}
