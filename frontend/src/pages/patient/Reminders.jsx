import {
  Alert,
  Button,
  Card,
  CardContent,
  CircularProgress,
  FormControl,
  FormControlLabel,
  InputLabel,
  MenuItem,
  Select,
  Stack,
  Switch,
  TextField,
  ToggleButton,
  ToggleButtonGroup,
  Typography,
} from '@mui/material';
import { useEffect, useState } from 'react';
import { api, errorMessage } from '../../api/client';

const BROWSER_TZ = Intl.DateTimeFormat().resolvedOptions().timeZone || 'America/Mexico_City';
// El despachador corre cada 15 minutos: solo horas en cuartos
const TIMES = Array.from({ length: (22 - 6) * 4 + 1 }, (_, i) => {
  const minutes = 6 * 60 + i * 15;
  return `${String(Math.floor(minutes / 60)).padStart(2, '0')}:${String(minutes % 60).padStart(2, '0')}`;
});
const CHANNELS = {
  in_app: ['in_app'],
  email: ['email'],
  ambos: ['in_app', 'email'],
};

const KINDS = [
  {
    kind: 'self_exam',
    title: 'Autoexploración',
    defaults: { frequency: 'first_sunday', interval_n: null, local_time: '09:00', channels: ['in_app'] },
  },
  {
    kind: 'repeat_analysis',
    title: 'Repetir análisis de imagen',
    defaults: { frequency: 'every_n_months', interval_n: 6, local_time: '09:00', channels: ['in_app', 'email'] },
  },
];

function channelKey(channels) {
  if (channels.length === 2) return 'ambos';
  return channels[0];
}

function fromServer(saved, defaults) {
  if (!saved) return { ...defaults, timezone: BROWSER_TZ, discreet: true, active: false, saved: false };
  return {
    frequency: saved.frequency,
    interval_n: saved.interval_n,
    local_time: saved.local_time.slice(0, 5),
    timezone: saved.timezone,
    channels: saved.channels,
    discreet: saved.discreet,
    active: saved.active,
    next_run_at: saved.next_run_at,
    saved: true,
  };
}

function ReminderCard({ title, value, onChange }) {
  const set = (patch) => onChange({ ...value, ...patch });
  const needsInterval = value.frequency !== 'first_sunday';

  return (
    <Card>
      <CardContent>
        <Stack spacing={2}>
          <Stack direction="row" sx={{ alignItems: 'center', justifyContent: 'space-between' }}>
            <Typography variant="h6" component="h2">
              {title}
            </Typography>
            <FormControlLabel
              control={<Switch checked={value.active} onChange={(e) => set({ active: e.target.checked })} />}
              label={value.active ? 'Activo' : 'Inactivo'}
              labelPlacement="start"
            />
          </Stack>
          <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2}>
            <FormControl fullWidth>
              <InputLabel id={`${title}-frecuencia`}>Frecuencia</InputLabel>
              <Select
                labelId={`${title}-frecuencia`}
                label="Frecuencia"
                value={value.frequency}
                onChange={(e) => {
                  const frequency = e.target.value;
                  const interval_n = frequency === 'first_sunday' ? null : frequency === 'every_n_days' ? 28 : 6;
                  set({ frequency, interval_n });
                }}
              >
                <MenuItem value="first_sunday">Primer domingo del mes</MenuItem>
                <MenuItem value="every_n_days">Cada cierto número de días</MenuItem>
                <MenuItem value="every_n_months">Cada cierto número de meses</MenuItem>
              </Select>
            </FormControl>
            {needsInterval && (
              <TextField
                label={value.frequency === 'every_n_days' ? 'Cada (días)' : 'Cada (meses)'}
                type="number"
                value={value.interval_n ?? ''}
                onChange={(e) => set({ interval_n: e.target.value === '' ? null : Number(e.target.value) })}
                slotProps={{ htmlInput: { min: 1, max: value.frequency === 'every_n_days' ? 90 : 24 } }}
                sx={{ maxWidth: { sm: 160 } }}
              />
            )}
            <FormControl sx={{ minWidth: 120 }}>
              <InputLabel id={`${title}-hora`}>Hora</InputLabel>
              <Select
                labelId={`${title}-hora`}
                label="Hora"
                value={value.local_time}
                onChange={(e) => set({ local_time: e.target.value })}
              >
                {TIMES.map((t) => (
                  <MenuItem key={t} value={t}>
                    {t}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
          </Stack>
          {value.frequency === 'first_sunday' && (
            <Typography variant="caption" color="text.secondary">
              Predeterminado: primer domingo del mes.
            </Typography>
          )}
          <Stack spacing={1}>
            <Typography variant="subtitle2" component="h3" id={`${title}-canal`}>
              Canal
            </Typography>
            <ToggleButtonGroup
              exclusive
              size="small"
              aria-labelledby={`${title}-canal`}
              value={channelKey(value.channels)}
              onChange={(_, key) => key && set({ channels: CHANNELS[key] })}
            >
              <ToggleButton value="in_app" sx={{ px: 2 }}>
                En la app
              </ToggleButton>
              <ToggleButton value="email" sx={{ px: 2 }}>
                Correo
              </ToggleButton>
              <ToggleButton value="ambos" sx={{ px: 2 }}>
                Ambos
              </ToggleButton>
            </ToggleButtonGroup>
          </Stack>
          {value.channels.includes('email') && (
            <FormControlLabel
              control={<Switch checked={value.discreet} onChange={(e) => set({ discreet: e.target.checked })} />}
              label="Notificaciones discretas: el correo no menciona el tema ni la aplicación"
            />
          )}
          <TextField
            label="Zona horaria"
            value={value.timezone}
            onChange={(e) => set({ timezone: e.target.value })}
            helperText="Se tomó de tu dispositivo. Ejemplo: America/Tijuana"
            size="small"
          />
          {value.saved && value.active && value.next_run_at && (
            <Typography variant="body2" color="text.secondary">
              Próximo aviso: {new Date(value.next_run_at).toLocaleString('es-MX', { dateStyle: 'full', timeStyle: 'short' })}
            </Typography>
          )}
        </Stack>
      </CardContent>
    </Card>
  );
}

export default function Reminders() {
  const [values, setValues] = useState(null);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState(null);

  useEffect(() => {
    api
      .get('/reminders')
      .then(({ data }) => {
        const byKind = Object.fromEntries(data.map((r) => [r.kind, r]));
        setValues(Object.fromEntries(KINDS.map(({ kind, defaults }) => [kind, fromServer(byKind[kind], defaults)])));
      })
      .catch((err) => setMessage({ severity: 'error', text: errorMessage(err, 'No se pudieron cargar.') }));
  }, []);

  async function saveAll() {
    setSaving(true);
    setMessage(null);
    try {
      const next = { ...values };
      for (const { kind } of KINDS) {
        const v = values[kind];
        // Uno nunca activado no se crea en el servidor
        if (!v.saved && !v.active) continue;
        const { data } = await api.put(`/reminders/${kind}`, {
          frequency: v.frequency,
          interval_n: v.frequency === 'first_sunday' ? null : v.interval_n,
          local_time: v.local_time,
          timezone: v.timezone,
          channels: v.channels,
          discreet: v.discreet,
          active: v.active,
        });
        next[kind] = fromServer(data);
      }
      setValues(next);
      setMessage({ severity: 'success', text: 'Recordatorios guardados.' });
    } catch (err) {
      setMessage({ severity: 'error', text: errorMessage(err, 'No se pudieron guardar.') });
    } finally {
      setSaving(false);
    }
  }

  return (
    <Stack spacing={2}>
      <Typography variant="h5" component="h1">
        Recordatorios
      </Typography>
      <Typography variant="body2" color="text.secondary">
        Te avisamos dentro de la app y, si quieres, por correo. Por ahora el correo está en modo de prueba.
      </Typography>
      {!values && !message && <CircularProgress sx={{ alignSelf: 'center' }} />}
      {values &&
        KINDS.map(({ kind, title }) => (
          <ReminderCard
            key={kind}
            title={title}
            value={values[kind]}
            onChange={(value) => setValues((current) => ({ ...current, [kind]: value }))}
          />
        ))}
      {message && <Alert severity={message.severity}>{message.text}</Alert>}
      {values && (
        <Button variant="contained" onClick={saveAll} disabled={saving}>
          Guardar recordatorios
        </Button>
      )}
    </Stack>
  );
}
