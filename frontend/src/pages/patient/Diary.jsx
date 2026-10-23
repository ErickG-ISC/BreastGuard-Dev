import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControl,
  FormControlLabel,
  IconButton,
  InputLabel,
  MenuItem,
  Select,
  Slider,
  Stack,
  Switch,
  Tab,
  Tabs,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material';
import { useEffect, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { api, errorMessage } from '../../api/client';
import BodyMap from '../../components/BodyMap';
import { DeleteIcon, DropIcon, EditIcon } from '../../components/icons';
import { SYMPTOM_LABELS, ZONE_LABELS, zoneDescription } from './symptomLabels';

// Fecha local de hoy en formato AAAA-MM-DD (el input date y el backend usan ese formato)
const today = () => new Date().toLocaleDateString('en-CA');

function emptyForm(prefill = {}) {
  return {
    entry_date: prefill.entryDate ?? today(),
    side: 'izquierdo',
    zone: null,
    symptoms: [],
    intensity: 3,
    note: '',
    self_exam_id: prefill.selfExamId ?? null,
    in_period: false,
    cycle_day: '',
  };
}

function fromEntry(entry) {
  return {
    entry_date: entry.entry_date,
    side: entry.side,
    zone: entry.zone,
    symptoms: entry.symptoms,
    intensity: entry.intensity,
    note: entry.note ?? '',
    self_exam_id: entry.self_exam_id,
    in_period: Boolean(entry.in_period),
    cycle_day: entry.cycle_day ?? '',
  };
}

function formatDay(isoDate) {
  // Fecha sin hora: se arma en local para que no se recorra un día por la zona horaria
  const [y, m, d] = isoDate.split('-').map(Number);
  return new Date(y, m - 1, d).toLocaleDateString('es-MX', { day: 'numeric', month: 'long', year: 'numeric' });
}

function EntryForm({ initial, editingId, onSaved, onCancel }) {
  const [form, setForm] = useState(initial);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const set = (patch) => setForm((current) => ({ ...current, ...patch }));

  const toggleSymptom = (code) =>
    set({
      symptoms: form.symptoms.includes(code) ? form.symptoms.filter((s) => s !== code) : [...form.symptoms, code],
    });

  async function save(event) {
    event.preventDefault();
    setSaving(true);
    setError('');
    const body = {
      entry_date: form.entry_date,
      side: form.side,
      zone: form.zone,
      symptoms: form.symptoms,
      intensity: form.intensity,
      note: form.note.trim() || null,
      self_exam_id: form.self_exam_id,
      in_period: form.in_period,
      cycle_day: form.cycle_day === '' ? null : Number(form.cycle_day),
    };
    try {
      const { data } = editingId ? await api.patch(`/symptoms/${editingId}`, body) : await api.post('/symptoms', body);
      onSaved(data);
    } catch (err) {
      setError(errorMessage(err, 'No se pudo guardar el registro.'));
    } finally {
      setSaving(false);
    }
  }

  const ready = form.zone && form.symptoms.length > 0 && form.entry_date;

  return (
    <Card>
      <CardContent>
        <Stack spacing={3} component="form" onSubmit={save}>
          {form.self_exam_id && (
            <Alert severity="info">Este registro quedará enlazado a tu autoexploración.</Alert>
          )}
          <TextField
            label="Fecha"
            type="date"
            value={form.entry_date}
            onChange={(e) => set({ entry_date: e.target.value })}
            slotProps={{ inputLabel: { shrink: true }, htmlInput: { max: today() } }}
          />
          <Box>
            <Typography variant="subtitle1" component="h2" sx={{ mb: 1 }}>
              Toca la zona exacta
            </Typography>
            <BodyMap value={{ side: form.side, zone: form.zone }} onChange={(v) => set(v)} />
          </Box>
          <Box>
            <Typography variant="subtitle1" component="h2" id="intensidad-label">
              Intensidad: {form.intensity} de 10
            </Typography>
            <Slider
              value={form.intensity}
              min={0}
              max={10}
              step={1}
              marks={[
                { value: 0, label: 'Leve' },
                { value: 10, label: 'Fuerte' },
              ]}
              onChange={(_, value) => set({ intensity: value })}
              aria-labelledby="intensidad-label"
              sx={{ mx: 1, width: 'calc(100% - 16px)' }}
            />
          </Box>
          <Box>
            <Typography variant="subtitle1" component="h2" sx={{ mb: 1 }}>
              Tipo de síntoma
            </Typography>
            <Stack direction="row" sx={{ flexWrap: 'wrap', gap: 1 }}>
              {Object.entries(SYMPTOM_LABELS).map(([code, label]) => {
                const selected = form.symptoms.includes(code);
                return (
                  <Chip
                    key={code}
                    label={label}
                    color={selected ? 'primary' : 'default'}
                    variant={selected ? 'filled' : 'outlined'}
                    onClick={() => toggleSymptom(code)}
                    aria-pressed={selected}
                  />
                );
              })}
            </Stack>
          </Box>
          <TextField
            label="Nota"
            placeholder="Escribe cómo te sentiste…"
            multiline
            minRows={3}
            value={form.note}
            onChange={(e) => set({ note: e.target.value })}
            slotProps={{ htmlInput: { maxLength: 2000 } }}
            helperText="Solo tú puedes verla."
          />
          <Accordion disableGutters variant="outlined" defaultExpanded={form.in_period || form.cycle_day !== ''}>
            <AccordionSummary>
              <Typography>Ciclo menstrual (opcional)</Typography>
            </AccordionSummary>
            <AccordionDetails>
              <Stack spacing={2}>
                <FormControlLabel
                  control={<Switch checked={form.in_period} onChange={(e) => set({ in_period: e.target.checked })} />}
                  label="Estoy en mi periodo"
                />
                <TextField
                  label="Día del ciclo"
                  type="number"
                  value={form.cycle_day}
                  onChange={(e) => set({ cycle_day: e.target.value })}
                  slotProps={{ htmlInput: { min: 1, max: 60 } }}
                  helperText="Cuenta desde el primer día de tu última regla."
                />
              </Stack>
            </AccordionDetails>
          </Accordion>
          {error && <Alert severity="error">{error}</Alert>}
          <Stack direction="row" spacing={1} sx={{ justifyContent: 'flex-end' }}>
            {editingId && <Button onClick={onCancel}>Cancelar</Button>}
            <Button type="submit" variant="contained" disabled={!ready || saving}>
              {editingId ? 'Guardar cambios' : 'Guardar registro'}
            </Button>
          </Stack>
        </Stack>
      </CardContent>
    </Card>
  );
}

function EntryCard({ entry, onEdit, onDelete }) {
  return (
    <Card>
      <CardContent>
        <Stack spacing={1}>
          <Stack direction="row" sx={{ alignItems: 'center', gap: 1 }}>
            <Typography variant="subtitle1" component="h3" sx={{ flexGrow: 1 }}>
              {formatDay(entry.entry_date)}
            </Typography>
            {entry.in_period && (
              <Tooltip title="En periodo">
                <DropIcon color="primary" aria-label="En periodo" role="img" fontSize="small" />
              </Tooltip>
            )}
            <IconButton aria-label="Editar registro" onClick={() => onEdit(entry)} size="small">
              <EditIcon fontSize="small" />
            </IconButton>
            <IconButton aria-label="Eliminar registro" onClick={() => onDelete(entry)} size="small">
              <DeleteIcon fontSize="small" />
            </IconButton>
          </Stack>
          <Typography variant="body2" color="text.secondary">
            {zoneDescription(entry.side, entry.zone)} · intensidad {entry.intensity}/10
            {entry.cycle_day ? ` · día ${entry.cycle_day} del ciclo` : ''}
          </Typography>
          <Stack direction="row" sx={{ flexWrap: 'wrap', gap: 0.5 }}>
            {entry.symptoms.map((code) => (
              <Chip key={code} size="small" label={SYMPTOM_LABELS[code]} />
            ))}
            {entry.self_exam_id && <Chip size="small" variant="outlined" label="De una autoexploración" />}
          </Stack>
          {entry.note && <Typography variant="body2">{entry.note}</Typography>}
        </Stack>
      </CardContent>
    </Card>
  );
}

const NO_FILTERS = { symptom: '', zone: '', from: '', to: '' };

function Timeline({ onEdit }) {
  const [filters, setFilters] = useState(NO_FILTERS);
  const [page, setPage] = useState(null);
  const [error, setError] = useState('');
  const [toDelete, setToDelete] = useState(null);
  const [reload, setReload] = useState(0);

  useEffect(() => {
    const params = Object.fromEntries(Object.entries(filters).filter(([, v]) => v !== ''));
    api
      .get('/symptoms', { params: { ...params, limit: 100 } })
      .then(({ data }) => {
        setPage(data);
        setError('');
      })
      .catch((err) => setError(errorMessage(err, 'No se pudo cargar tu diario.')));
  }, [filters, reload]);

  async function confirmDelete() {
    try {
      await api.delete(`/symptoms/${toDelete.id}`);
      setReload((n) => n + 1);
    } catch (err) {
      setError(errorMessage(err, 'No se pudo eliminar.'));
    } finally {
      setToDelete(null);
    }
  }

  const setFilter = (patch) => setFilters((current) => ({ ...current, ...patch }));

  return (
    <Stack spacing={2}>
      <Card>
        <CardContent>
          <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2} sx={{ flexWrap: 'wrap' }}>
            <FormControl size="small" sx={{ minWidth: 180 }}>
              <InputLabel id="f-sintoma">Síntoma</InputLabel>
              <Select
                labelId="f-sintoma"
                label="Síntoma"
                value={filters.symptom}
                onChange={(e) => setFilter({ symptom: e.target.value })}
              >
                <MenuItem value="">Todos</MenuItem>
                {Object.entries(SYMPTOM_LABELS).map(([code, label]) => (
                  <MenuItem key={code} value={code}>
                    {label}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
            <FormControl size="small" sx={{ minWidth: 220 }}>
              <InputLabel id="f-zona">Zona</InputLabel>
              <Select labelId="f-zona" label="Zona" value={filters.zone} onChange={(e) => setFilter({ zone: e.target.value })}>
                <MenuItem value="">Todas</MenuItem>
                {Object.entries(ZONE_LABELS).map(([code, label]) => (
                  <MenuItem key={code} value={code}>
                    {label}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
            <TextField
              size="small"
              label="Desde"
              type="date"
              value={filters.from}
              onChange={(e) => setFilter({ from: e.target.value })}
              slotProps={{ inputLabel: { shrink: true } }}
              sx={{ width: { sm: 170 } }}
            />
            <TextField
              size="small"
              label="Hasta"
              type="date"
              value={filters.to}
              onChange={(e) => setFilter({ to: e.target.value })}
              slotProps={{ inputLabel: { shrink: true } }}
              sx={{ width: { sm: 170 } }}
            />
          </Stack>
          {filters !== NO_FILTERS && (
            <Button size="small" onClick={() => setFilters(NO_FILTERS)} sx={{ mt: 1 }}>
              Quitar filtros
            </Button>
          )}
        </CardContent>
      </Card>
      {error && <Alert severity="error">{error}</Alert>}
      {!page && !error && <CircularProgress sx={{ alignSelf: 'center' }} />}
      {page && page.items.length === 0 && (
        <Typography variant="body2" color="text.secondary">
          No hay registros con estos filtros.
        </Typography>
      )}
      {page?.items.map((entry) => (
        <EntryCard key={entry.id} entry={entry} onEdit={onEdit} onDelete={setToDelete} />
      ))}
      <Typography variant="caption" color="text.secondary" sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
        <DropIcon fontSize="inherit" color="primary" /> = registro durante tu periodo
      </Typography>
      <Dialog open={Boolean(toDelete)} onClose={() => setToDelete(null)}>
        <DialogTitle>¿Eliminar este registro?</DialogTitle>
        <DialogContent>
          <Typography variant="body2">Se borra de forma definitiva y no se puede recuperar.</Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setToDelete(null)}>Cancelar</Button>
          <Button color="error" variant="contained" onClick={confirmDelete}>
            Eliminar
          </Button>
        </DialogActions>
      </Dialog>
    </Stack>
  );
}

export default function Diary() {
  const location = useLocation();
  const navigate = useNavigate();
  const [tab, setTab] = useState(0);
  const [editing, setEditing] = useState(null);
  const [formKey, setFormKey] = useState(0);
  const [saved, setSaved] = useState(false);
  // Prellenado desde la autoexploración (fecha y enlace); solo para el primer formulario
  const [prefill] = useState(() => location.state ?? {});

  function handleSaved() {
    setEditing(null);
    setSaved(true);
    setFormKey((k) => k + 1);
    setTab(1);
    // El prellenado ya se usó: no debe volver a aparecer al regresar a la página
    navigate(location.pathname, { replace: true, state: null });
  }

  function handleEdit(entry) {
    setEditing(entry);
    setSaved(false);
    setTab(0);
  }

  const initial = editing ? fromEntry(editing) : emptyForm(formKey === 0 ? prefill : {});

  return (
    <Stack spacing={2}>
      <Typography variant="h5" component="h1">
        Diario
      </Typography>
      <Tabs value={tab} onChange={(_, value) => setTab(value)} variant="fullWidth" aria-label="Secciones del diario">
        <Tab label={editing ? 'Editar' : 'Registrar'} />
        <Tab label="Línea de tiempo" />
      </Tabs>
      {saved && tab === 1 && (
        <Alert severity="success" onClose={() => setSaved(false)}>
          Registro guardado. Si un cambio persiste o te preocupa, consulta a tu médico.
        </Alert>
      )}
      {tab === 0 && (
        <EntryForm
          key={editing ? editing.id : `nuevo-${formKey}`}
          initial={initial}
          editingId={editing?.id}
          onSaved={handleSaved}
          onCancel={() => {
            setEditing(null);
            setTab(1);
          }}
        />
      )}
      {tab === 1 && <Timeline onEdit={handleEdit} />}
    </Stack>
  );
}
