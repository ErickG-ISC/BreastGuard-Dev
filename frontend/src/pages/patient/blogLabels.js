// Etiquetas del blog (CU-06) y recomendación por el último análisis de la paciente.
export const TAG_LABELS = {
  'bi-rads': 'BI-RADS',
  resultados: 'Resultados',
  ecografia: 'Ecografía',
  estudios: 'Estudios',
  autoexploracion: 'Autoexploración',
  prevencion: 'Prevención',
  'cuando-consultar': 'Cuándo consultar',
  'sobre-la-app': 'Sobre la app',
};

// Etiqueta recomendada según el último análisis (sin análisis: qué hace la app). El blog nunca
// recibe este dato: la recomendación se arma en el navegador.
export function recommendedTag(lastAnalysis) {
  if (!lastAnalysis) return 'sobre-la-app';
  if (lastAnalysis.status === 'inconclusive' || lastAnalysis.predicted_class === 'maligno') return 'cuando-consultar';
  if (lastAnalysis.predicted_class === 'benigno') return 'bi-rads';
  return 'autoexploracion';
}

export function reviewLabel(article) {
  // Nunca "validado": sin revisor declarado es contenido educativo general
  if (article.reviewed_by) return `Revisado por ${article.reviewed_by}`;
  return 'Contenido educativo general · borrador';
}
