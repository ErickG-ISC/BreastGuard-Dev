import {
  AnalyzeIcon,
  DiaryIcon,
  HistoryIcon,
  HomeIcon,
  MoreIcon,
  QuestionnaireIcon,
} from './icons';

// Secciones principales: barra inferior en móvil y primera parte de la barra lateral
export const PRIMARY_NAV = [
  { label: 'Inicio', to: '/paciente', icon: HomeIcon },
  { label: 'Analizar', to: '/analizar', icon: AnalyzeIcon },
  { label: 'Historial', to: '/historial', icon: HistoryIcon, also: ['/resultado'] },
  { label: 'Diario', to: '/diario', icon: DiaryIcon },
  { label: 'Más', to: '/mas', icon: MoreIcon },
];

// Secciones de "Más": página propia en móvil, visibles directo en la barra lateral de escritorio
export const SECONDARY_NAV = [
  { label: 'Cuestionario', to: '/cuestionario', icon: QuestionnaireIcon },
];

function matches(item, pathname) {
  return [item.to, ...(item.also ?? [])].some((p) => pathname === p || pathname.startsWith(`${p}/`));
}

// Pestaña activa de la barra inferior; las secciones secundarias cuentan como "Más"
export function activePrimary(pathname) {
  const direct = PRIMARY_NAV.find((item) => matches(item, pathname));
  if (direct) return direct.to;
  if (SECONDARY_NAV.some((item) => matches(item, pathname))) return '/mas';
  return false;
}

export function isActive(item, pathname) {
  return matches(item, pathname);
}
