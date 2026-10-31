// Textos de la administración (ADR 0008). El backend solo devuelve códigos.
export const ROLE_LABELS = {
  tenant_admin: 'Administración',
  doctor: 'Médico/a',
  patient: 'Paciente',
  platform_admin: 'Admin de plataforma',
  system: 'Sistema',
  user: 'La propia persona',
};

export const STATUS_LABELS = {
  invited: { label: 'Invitación pendiente', color: 'info' },
  active: { label: 'Activo', color: 'success' },
  inactive: { label: 'Inactivo', color: 'default' },
};

export const PLAN_LABELS = { basic: 'Básico', pro: 'Pro', enterprise: 'Enterprise' };

export const ACTION_LABELS = {
  'tenant.create': 'Alta de institución',
  'tenant.update': 'Edición de institución',
  'tenant.activate': 'Institución reactivada',
  'tenant.deactivate': 'Institución desactivada',
  'tenant.purge_request': 'Purga solicitada',
  'tenant.purge_cancel': 'Purga cancelada',
  'tenant.purge': 'Purga ejecutada',
  'user.invite': 'Invitación enviada',
  'user.invite_resend': 'Invitación reenviada',
  'user.invite_accept': 'Invitación aceptada',
  'user.access_reset': 'Acceso restablecido',
  'user.activate': 'Usuario reactivado',
  'user.deactivate': 'Usuario desactivado',
  'user.role_change': 'Cambio de rol',
  'handover.create': 'Traspaso de pacientes creado',
  'handover.accept': 'Traspaso de pacientes aceptado',
  'handover.cancel': 'Traspaso de pacientes cancelado',
};

export function formatDateTime(iso) {
  if (!iso) return '—';
  return new Date(iso).toLocaleString('es-MX', { dateStyle: 'medium', timeStyle: 'short' });
}

export function emailNotice(sent) {
  return sent
    ? 'Se envió la invitación por correo.'
    : 'La cuenta quedó creada, pero no se pudo enviar el correo. Usa "Reenviar invitación" cuando el correo esté configurado.';
}
