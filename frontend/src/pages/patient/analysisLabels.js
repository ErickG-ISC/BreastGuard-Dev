// Textos y colores compartidos por las pantallas de análisis (lenguaje sencillo).
export const LEVEL_SEVERITY = {
  attention: 'warning',
  inconclusive: 'info',
  benign_pattern: 'info',
  no_findings: 'success',
};

export const CLASS_LABELS = {
  normal: 'Sin hallazgos destacados',
  benigno: 'Hallazgo de aspecto benigno',
  maligno: 'Hallazgo que conviene revisar',
};

// Un resultado no concluyente nunca muestra la clase cruda (podría leerse como "todo bien")
export function resultLabel(analysis) {
  if (analysis.report.level === 'inconclusive') return 'No concluyente';
  return CLASS_LABELS[analysis.predicted_class] ?? analysis.report.summary;
}

export function formatDate(iso) {
  return new Date(iso).toLocaleString('es-MX', { dateStyle: 'medium', timeStyle: 'short' });
}
