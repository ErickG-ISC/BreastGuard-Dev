// Pantalla inicial según el rol del usuario autenticado
export function homeFor(role) {
  return role === 'platform_admin' ? '/admin/tenants' : '/';
}
