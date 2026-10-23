// Textos para la paciente de los códigos fijos del diario (CU-04). El backend solo guarda códigos.
export const SIDE_LABELS = {
  izquierdo: 'Izquierda',
  derecho: 'Derecha',
  ambos: 'Ambas',
};

export const ZONE_LABELS = {
  superior_externo: 'Cuadrante superior externo',
  superior_interno: 'Cuadrante superior interno',
  inferior_externo: 'Cuadrante inferior externo',
  inferior_interno: 'Cuadrante inferior interno',
  areola_pezon: 'Areola y pezón',
  axila: 'Axila',
  otra: 'Otra zona',
};

export const SYMPTOM_LABELS = {
  bulto: 'Bulto',
  dolor: 'Dolor',
  sensibilidad: 'Sensibilidad',
  secrecion: 'Secreción',
  cambio_piel: 'Cambio en la piel',
  cambio_pezon: 'Cambio en el pezón',
  enrojecimiento: 'Enrojecimiento',
  otro: 'Otro',
};

export function zoneDescription(side, zone) {
  const where = side === 'ambos' ? 'Ambas mamas' : `Mama ${SIDE_LABELS[side].toLowerCase()}`;
  return `${where} · ${ZONE_LABELS[zone]}`;
}
