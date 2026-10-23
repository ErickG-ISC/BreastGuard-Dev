import { Box, FormControl, InputLabel, MenuItem, Select, Stack, ToggleButton, ToggleButtonGroup } from '@mui/material';
import { SIDE_LABELS, ZONE_LABELS } from '../pages/patient/symptomLabels';

// Mapa corporal accesible (CU-04): cada zona es un botón con teclado (Enter o Espacio) y
// nombre accesible; debajo, el mismo dato se elige con controles estándar (lado y lista).
// Vista frontal: la mama izquierda se dibuja a la izquierda, como en el wireframe M08, y cada
// lado lleva su rótulo para evitar confusiones.

const R = 46;
const BREASTS = {
  izquierdo: { cx: 88, cy: 120, outward: -1 },
  derecho: { cx: 212, cy: 120, outward: 1 },
};

function wedge(cx, cy, startDeg, endDeg) {
  const rad = (d) => (d * Math.PI) / 180;
  const x1 = cx + R * Math.cos(rad(startDeg));
  const y1 = cy + R * Math.sin(rad(startDeg));
  const x2 = cx + R * Math.cos(rad(endDeg));
  const y2 = cy + R * Math.sin(rad(endDeg));
  return `M${cx} ${cy}L${x1.toFixed(1)} ${y1.toFixed(1)}A${R} ${R} 0 0 1 ${x2.toFixed(1)} ${y2.toFixed(1)}Z`;
}

// Ángulos SVG (0° a la derecha, crecen hacia abajo). "Externo" es hacia afuera del cuerpo.
function quadrants(outward) {
  const outerUpper = outward < 0 ? [180, 270] : [270, 360];
  const innerUpper = outward < 0 ? [270, 360] : [180, 270];
  const outerLower = outward < 0 ? [90, 180] : [0, 90];
  const innerLower = outward < 0 ? [0, 90] : [90, 180];
  return {
    superior_externo: outerUpper,
    superior_interno: innerUpper,
    inferior_externo: outerLower,
    inferior_interno: innerLower,
  };
}

function Zone({ side, zone, selected, onSelect, children }) {
  const label = `Mama ${SIDE_LABELS[side].toLowerCase()}, ${ZONE_LABELS[zone].toLowerCase()}`;
  return (
    <Box
      component="g"
      role="button"
      tabIndex={0}
      aria-label={label}
      aria-pressed={selected}
      onClick={() => onSelect(side, zone)}
      onKeyDown={(event) => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault();
          onSelect(side, zone);
        }
      }}
      sx={{
        cursor: 'pointer',
        outline: 'none',
        '& > *': {
          fill: selected ? 'var(--mui-palette-primary-main)' : 'var(--mui-palette-action-hover)',
          fillOpacity: selected ? 0.75 : 1,
          stroke: 'var(--mui-palette-text-secondary)',
          strokeWidth: 1.5,
        },
        '&:hover > *': { fill: selected ? undefined : 'var(--mui-palette-action-selected)' },
        '&:focus-visible > *': { stroke: 'var(--mui-palette-primary-main)', strokeWidth: 4 },
      }}
    >
      {children}
    </Box>
  );
}

function Breast({ side, value, onSelect }) {
  const { cx, cy, outward } = BREASTS[side];
  const isSelected = (zone) => value.zone === zone && (value.side === side || value.side === 'ambos');
  return (
    <g>
      <text x={cx} y={cy - R - 34} textAnchor="middle" fontSize="15" fill="currentColor" fontWeight="600">
        {side === 'izquierdo' ? 'I · Izquierda' : 'D · Derecha'}
      </text>
      <Zone side={side} zone="axila" selected={isSelected('axila')} onSelect={onSelect}>
        <ellipse cx={cx + outward * 58} cy={cy - 50} rx="18" ry="13" />
      </Zone>
      {Object.entries(quadrants(outward)).map(([zone, [start, end]]) => (
        <Zone key={zone} side={side} zone={zone} selected={isSelected(zone)} onSelect={onSelect}>
          <path d={wedge(cx, cy, start, end)} />
        </Zone>
      ))}
      <Zone side={side} zone="areola_pezon" selected={isSelected('areola_pezon')} onSelect={onSelect}>
        <circle cx={cx} cy={cy} r="13" />
      </Zone>
    </g>
  );
}

export default function BodyMap({ value, onChange }) {
  const select = (side, zone) => {
    // Con "ambas" marcado, tocar una zona conserva ambos lados
    onChange({ side: value.side === 'ambos' ? 'ambos' : side, zone });
  };

  return (
    <Stack spacing={2}>
      <Box sx={{ color: 'text.secondary', display: 'flex', justifyContent: 'center' }}>
        <Box
          component="svg"
          viewBox="0 0 300 200"
          role="group"
          aria-label="Mapa corporal: toca la zona exacta"
          sx={{ width: '100%', maxWidth: 360 }}
        >
          {/* contorno del torso */}
          <path d="M20 40q130-40 260 0M30 44q-8 80 6 150M270 44q8 80-6 150" fill="none" stroke="currentColor" strokeWidth="2" opacity="0.5" />
          <Breast side="izquierdo" value={value} onSelect={select} />
          <Breast side="derecho" value={value} onSelect={select} />
        </Box>
      </Box>
      <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2} sx={{ alignItems: { sm: 'center' } }}>
        <ToggleButtonGroup
          exclusive
          size="small"
          value={value.side}
          onChange={(_, side) => side && onChange({ ...value, side })}
          aria-label="Lado"
        >
          {Object.entries(SIDE_LABELS).map(([code, label]) => (
            <ToggleButton key={code} value={code} sx={{ px: 2 }}>
              {label}
            </ToggleButton>
          ))}
        </ToggleButtonGroup>
        <FormControl size="small" sx={{ minWidth: 240, flexGrow: 1 }}>
          <InputLabel id="zona-label">Zona</InputLabel>
          <Select
            labelId="zona-label"
            label="Zona"
            value={value.zone ?? ''}
            onChange={(event) => onChange({ ...value, zone: event.target.value })}
          >
            {Object.entries(ZONE_LABELS).map(([code, label]) => (
              <MenuItem key={code} value={code}>
                {label}
              </MenuItem>
            ))}
          </Select>
        </FormControl>
      </Stack>
    </Stack>
  );
}
