// Textos del panel y del caso de la médica (vocabulario técnico, no el de la paciente).
export const STATUS = {
  pendiente: { label: 'Pendiente', color: 'warning' },
  en_revision: { label: 'En revisión', color: 'info' },
  revisado: { label: 'Revisado', color: 'success' },
};

export const ORIGIN = { importado: 'Importada', creado: 'Alta en la institución' };

export const FILTERS = [
  { value: 'todas', label: 'Todas' },
  { value: 'pendientes', label: 'Pendientes de revisión' },
  { value: 'sospechosos', label: 'Casos sospechosos' },
  { value: 'revisadas', label: 'Revisadas' },
];

const CLASS = { normal: 'Normal', benigno: 'Benigno', maligno: 'Maligno' };

// "Sospechoso" y "No concluyente" los decide el servidor (una sola fuente: MLSettings)
export function resultText(analysis) {
  if (!analysis) return 'Sin análisis';
  if (analysis.suspicious) return 'Sospechoso';
  if (analysis.inconclusive || analysis.status === 'inconclusive') return 'No concluyente';
  return CLASS[analysis.predicted_class] ?? analysis.predicted_class;
}

export function resultColor(analysis) {
  if (!analysis) return 'default';
  if (analysis.suspicious) return 'error';
  if (analysis.inconclusive || analysis.status === 'inconclusive') return 'info';
  return 'default';
}

export function percent(value) {
  return `${Math.round(value * 100)} %`;
}

// Una fecha sin hora (AAAA-MM-DD) es un día del calendario: se lee como fecha LOCAL. Con
// new Date('2026-11-04') sería la medianoche UTC y en México se mostraría el día anterior.
function parse(value) {
  const day = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  return day ? new Date(Number(day[1]), Number(day[2]) - 1, Number(day[3])) : new Date(value);
}

export function formatDate(value) {
  return parse(value).toLocaleDateString('es-MX', { dateStyle: 'medium' });
}

export function formatDateTime(iso) {
  return new Date(iso).toLocaleString('es-MX', { dateStyle: 'medium', timeStyle: 'short' });
}

export const SIDE = { izquierdo: 'seno izq.', derecho: 'seno der.', ambos: 'ambos senos' };
export const ZONE = {
  superior_externo: 'cuadrante superior externo',
  superior_interno: 'cuadrante superior interno',
  inferior_externo: 'cuadrante inferior externo',
  inferior_interno: 'cuadrante inferior interno',
  areola_pezon: 'areola y pezón',
  axila: 'axila',
  otra: 'otra zona',
};
export const SYMPTOM = {
  bulto: 'Bulto',
  dolor: 'Dolor',
  sensibilidad: 'Sensibilidad',
  secrecion: 'Secreción',
  cambio_piel: 'Cambio en la piel',
  cambio_pezon: 'Cambio en el pezón',
  enrojecimiento: 'Enrojecimiento',
  otro: 'Otro',
};
export const NOTICED = { si: 'Notó un cambio', no: 'Sin cambios', no_segura: 'No está segura' };
