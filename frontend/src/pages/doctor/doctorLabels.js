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

// Mismo texto que backend/app/ml/profiles.py (se muestra también antes de subir un DICOM)
export const PROTOTYPE_WARNING =
  'Prototipo: el modelo se entrenó con ecografías y no está validado para mastografías.';

export const VIEW = { CC: 'craneocaudal (CC)', MLO: 'mediolateral oblicua (MLO)' };
export const LATERALITY = { L: 'izquierda', R: 'derecha' };

// Categorías BI-RADS que asigna la médica (el modelo nunca las sugiere)
export const BIRADS = [
  { value: '0', label: '0 · Evaluación incompleta' },
  { value: '1', label: '1 · Negativo' },
  { value: '2', label: '2 · Hallazgo benigno' },
  { value: '3', label: '3 · Probablemente benigno' },
  { value: '4', label: '4 · Sospechoso' },
  { value: '4A', label: '4A · Baja sospecha' },
  { value: '4B', label: '4B · Sospecha moderada' },
  { value: '4C', label: '4C · Alta sospecha' },
  { value: '5', label: '5 · Altamente sugestivo de malignidad' },
  { value: '6', label: '6 · Malignidad comprobada por biopsia' },
];
