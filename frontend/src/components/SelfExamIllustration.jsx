import { Box } from '@mui/material';

// Ilustraciones esquemáticas propias (líneas simples, sin fotos ni material de terceros).
// Usan currentColor y el color primario del tema para verse bien en claro y oscuro.
const stroke = { fill: 'none', stroke: 'currentColor', strokeWidth: 3, strokeLinecap: 'round', strokeLinejoin: 'round' };
const accent = { fill: 'none', stroke: 'var(--mui-palette-primary-main)', strokeWidth: 3, strokeLinecap: 'round' };

function Torso({ arms }) {
  return (
    <g>
      <circle cx="120" cy="38" r="17" {...stroke} />
      <path d="M112 55v10M128 55v10" {...stroke} />
      {/* hombros y costados */}
      <path d="M78 72q42-14 84 0M84 74q-6 60 6 116M156 74q6 60-6 116" {...stroke} />
      {/* mamas */}
      <path d="M90 112q15 26 30 2M120 114q15 24 30-2" {...stroke} />
      <circle cx="104" cy="120" r="2.5" fill="currentColor" />
      <circle cx="136" cy="120" r="2.5" fill="currentColor" />
      {arms === 'down' && <path d="M78 72q-12 50-8 110M162 72q12 50 8 110" {...stroke} />}
      {arms === 'up' && <path d="M80 72q-14-30-6-62M160 72q14-30 6-62" {...stroke} />}
      {arms === 'hips' && <path d="M78 72q-26 40-4 96l14 6M162 72q26 40 4 96l-14 6" {...stroke} />}
    </g>
  );
}

function Mirror({ children }) {
  return (
    <g>
      <rect x="40" y="8" width="160" height="190" rx="14" {...stroke} strokeDasharray="6 8" opacity="0.5" />
      {children}
    </g>
  );
}

function Lying({ side }) {
  // Cuerpo acostado de lado; los círculos marcan el recorrido con las yemas de los dedos
  const breastX = side === 'left' ? 100 : 150;
  return (
    <g>
      <path d="M20 150h200" {...stroke} opacity="0.4" />
      <rect x="22" y="112" width="34" height="14" rx="7" {...stroke} opacity="0.6" />
      <circle cx="44" cy="100" r="15" {...stroke} />
      <path d="M60 104q70-22 150 0M60 140h150M210 104v36" {...stroke} />
      <path d={`M${breastX - 20} 104q20-22 40 0`} {...stroke} />
      <circle cx={breastX} cy="96" r="7" {...accent} />
      <circle cx={breastX} cy="96" r="15" {...accent} strokeDasharray="4 6" />
      <circle cx={breastX} cy="96" r="23" {...accent} strokeDasharray="4 8" opacity="0.7" />
      <path d={`M${breastX + 30} 60q-10 16-18 22`} {...stroke} />
    </g>
  );
}

function ArmpitNipple() {
  return (
    <g>
      <path d="M40 60q50-20 100 10q40 30 30 80q-10 40-60 40q-50 0-60-40" {...stroke} />
      <circle cx="120" cy="140" r="12" {...stroke} />
      <circle cx="120" cy="140" r="3" fill="currentColor" />
      <circle cx="58" cy="78" r="18" {...accent} strokeDasharray="4 6" />
      <path d="M150 196q20-20 40-24" {...stroke} />
    </g>
  );
}

const DRAWINGS = {
  mirror_arms_down: (
    <Mirror>
      <Torso arms="down" />
    </Mirror>
  ),
  mirror_arms_up: (
    <Mirror>
      <Torso arms="up" />
    </Mirror>
  ),
  mirror_hands_hips: (
    <Mirror>
      <Torso arms="hips" />
    </Mirror>
  ),
  lying_left: <Lying side="left" />,
  lying_right: <Lying side="right" />,
  armpit_nipple: <ArmpitNipple />,
};

export default function SelfExamIllustration({ name, label }) {
  return (
    <Box sx={{ display: 'flex', justifyContent: 'center', color: 'text.secondary' }}>
      <Box component="svg" viewBox="0 0 240 210" role="img" aria-label={label} sx={{ width: '100%', maxWidth: 320 }}>
        {DRAWINGS[name] ?? null}
      </Box>
    </Box>
  );
}
