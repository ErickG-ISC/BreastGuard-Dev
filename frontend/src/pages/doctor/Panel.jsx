import {
  Alert,
  Box,
  Button,
  Card,
  CardActionArea,
  CardContent,
  Chip,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Grid,
  InputAdornment,
  Stack,
  Tab,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  Tabs,
  TextField,
  Typography,
  useMediaQuery,
} from '@mui/material';
import { useCallback, useEffect, useRef, useState } from 'react';
import { Navigate, Link as RouterLink, useNavigate } from 'react-router-dom';
import { api, errorMessage } from '../../api/client';
import { SearchIcon } from '../../components/icons';
import { DISCLAIMER } from '../../components/Layout';
import { PENDING_CODE_KEY } from '../ImportLink';
import { FILTERS, STATUS, formatDate, formatDateTime, percent, resultColor, resultText } from './doctorLabels';

const PAGE = 20;

function hasPendingCode() {
  try {
    return Boolean(sessionStorage.getItem(PENDING_CODE_KEY));
  } catch {
    return false;
  }
}

function Counter({ label, value, color }) {
  return (
    <Card sx={{ height: '100%' }}>
      <CardContent>
        <Typography variant="body2" color="text.secondary">
          {label}
        </Typography>
        <Typography variant="h4" component="p" color={color}>
          {value ?? '—'}
        </Typography>
      </CardContent>
    </Card>
  );
}

function HandoverMark({ row }) {
  if (row.handover_from) return <Chip size="small" variant="outlined" label={`Traspaso de ${row.handover_from}`} />;
  if (row.handover_to) return <Chip size="small" variant="outlined" label={`Traspasándose a ${row.handover_to}`} />;
  return null;
}

// Traspasos hacia ella y aviso de paquetes recibidos (antes en la página temporal /medico)
function Inbox() {
  const [handovers, setHandovers] = useState([]);
  const [notices, setNotices] = useState([]);
  const [message, setMessage] = useState(null);
  const [busy, setBusy] = useState(false);
  const busyRef = useRef(false);

  const load = useCallback(() => {
    api.get('/doctor/handovers').then(({ data }) => setHandovers(data)).catch(() => setHandovers([]));
    api
      .get('/doctor/notices')
      .then(({ data }) => setNotices(data.filter((n) => !n.read_at)))
      .catch(() => setNotices([]));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function accept(item) {
    if (busyRef.current) return;
    busyRef.current = true;
    setBusy(true);
    try {
      const { data } = await api.post(`/doctor/handovers/${item.id}/accept`);
      setMessage({ severity: 'success', text: `Ahora eres la médica responsable de ${data.patients_moved} pacientes de ${item.from_name}.` });
      load();
    } catch (err) {
      setMessage({ severity: 'error', text: errorMessage(err, 'No se pudo aceptar el traspaso.') });
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  }

  return (
    <Stack spacing={1}>
      {message && (
        <Alert severity={message.severity} onClose={() => setMessage(null)}>
          {message.text}
        </Alert>
      )}
      {notices.some((n) => n.kind === 'share_received') && (
        <Alert
          severity="info"
          action={
            <Button color="inherit" size="small" component={RouterLink} to="/medico/importar">
              Importar
            </Button>
          }
        >
          Una paciente compartió un paquete contigo. Pídele el código o abre su enlace para importarlo.
        </Alert>
      )}
      {handovers.map((item) => (
        <Alert
          key={item.id}
          severity="warning"
          action={
            <Button color="inherit" size="small" disabled={busy} onClick={() => accept(item)}>
              Aceptar
            </Button>
          }
        >
          La administración te traspasó las pacientes de {item.from_name} ({formatDateTime(item.created_at)}). Ya
          aparecen en tu lista; al aceptar pasas a ser su médica responsable.
        </Alert>
      ))}
    </Stack>
  );
}

// Alta manual de una ficha de la institución (origen "creado", ella como responsable)
function NewPatientDialog({ open, onClose, onCreated }) {
  const [name, setName] = useState('');
  const [age, setAge] = useState('');
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);

  async function submit(event) {
    event.preventDefault();
    setSaving(true);
    setError('');
    try {
      const { data } = await api.post('/doctor/patients', {
        display_name: name.trim(),
        age_years: age === '' ? null : Number(age),
      });
      onCreated(data.id);
    } catch (err) {
      setError(errorMessage(err, 'No se pudo dar de alta.'));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open={open} onClose={onClose} fullWidth maxWidth="xs">
      <form onSubmit={submit}>
        <DialogTitle>Nueva paciente</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 1 }}>
            {error && <Alert severity="error">{error}</Alert>}
            <TextField label="Nombre" value={name} onChange={(e) => setName(e.target.value)} required />
            <TextField
              label="Edad (años)"
              type="number"
              value={age}
              onChange={(e) => setAge(e.target.value)}
              slotProps={{ htmlInput: { min: 0, max: 120 } }}
              helperText="Se guarda la edad de hoy, no la fecha de nacimiento."
            />
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={onClose}>Cancelar</Button>
          <Button type="submit" variant="contained" disabled={!name.trim() || saving}>
            Dar de alta
          </Button>
        </DialogActions>
      </form>
    </Dialog>
  );
}

// CU-11: panel de pacientes (D01). La búsqueda va por POST: el nombre nunca en la URL.
export default function Panel() {
  const desktop = useMediaQuery((theme) => theme.breakpoints.up('md'));
  const navigate = useNavigate();
  const [pending] = useState(hasPendingCode);
  const [summary, setSummary] = useState(null);
  const [filter, setFilter] = useState('todas');
  const [query, setQuery] = useState('');
  const [debounced, setDebounced] = useState('');
  const [offset, setOffset] = useState(0);
  const [page, setPage] = useState(null);
  const [error, setError] = useState('');
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    const timer = setTimeout(() => setDebounced(query.trim()), 300);
    return () => clearTimeout(timer);
  }, [query]);

  useEffect(() => {
    api
      .get('/doctor/patients/summary')
      .then(({ data }) => setSummary(data))
      .catch(() => setSummary(null));
  }, []);

  useEffect(() => {
    let active = true;
    api
      .post('/doctor/patients/search', { filter, q: debounced || null, limit: PAGE, offset })
      .then(({ data }) => {
        if (!active) return;
        setPage(data);
        setError('');
      })
      .catch((err) => active && setError(errorMessage(err, 'No se pudo cargar la lista de pacientes.')));
    return () => {
      active = false;
    };
  }, [filter, debounced, offset]);

  if (pending) return <Navigate to="/medico/importar" replace />;

  const rows = page?.items ?? [];
  const open = (id) => navigate(`/medico/pacientes/${id}`);

  return (
    <Stack spacing={2}>
      <Stack direction="row" sx={{ justifyContent: 'space-between', alignItems: 'center', gap: 1, flexWrap: 'wrap' }}>
        <Typography variant="h5" component="h1">
          Panel
        </Typography>
        <Stack direction="row" spacing={1}>
          <Button variant="contained" onClick={() => setCreating(true)}>
            Nueva paciente
          </Button>
          <Button variant="outlined" component={RouterLink} to="/medico/importar">
            Importar paquete
          </Button>
        </Stack>
      </Stack>
      <NewPatientDialog
        open={creating}
        onClose={() => setCreating(false)}
        onCreated={(id) => navigate(`/medico/pacientes/${id}`)}
      />
      <Inbox />
      <Grid container spacing={2}>
        <Grid size={{ xs: 12, sm: 4 }}>
          <Counter label="Pendientes de revisión" value={summary?.pending_review} />
        </Grid>
        <Grid size={{ xs: 6, sm: 4 }}>
          <Counter label="Casos sospechosos" value={summary?.suspicious} color="error" />
        </Grid>
        <Grid size={{ xs: 6, sm: 4 }}>
          <Counter label="Pacientes activas" value={summary?.active} />
        </Grid>
      </Grid>

      <Stack direction={{ xs: 'column', md: 'row' }} sx={{ gap: 1, alignItems: { md: 'center' }, justifyContent: 'space-between' }}>
        <Tabs
          sx={{ minWidth: 0 }}
          value={filter}
          onChange={(_, value) => {
            setFilter(value);
            setOffset(0);
          }}
          variant="scrollable"
          allowScrollButtonsMobile
          aria-label="Filtro de pacientes"
        >
          {FILTERS.map((f) => (
            <Tab key={f.value} value={f.value} label={f.label} />
          ))}
        </Tabs>
        <TextField
          size="small"
          sx={{ width: { xs: '100%', md: 280 }, flexShrink: 0 }}
          placeholder="Buscar por nombre"
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setOffset(0);
          }}
          slotProps={{
            input: {
              startAdornment: (
                <InputAdornment position="start">
                  <SearchIcon fontSize="small" />
                </InputAdornment>
              ),
            },
            htmlInput: { 'aria-label': 'Buscar paciente por nombre', maxLength: 100 },
          }}
        />
      </Stack>

      {error && <Alert severity="error">{error}</Alert>}
      {!page && !error && <CircularProgress sx={{ alignSelf: 'center' }} />}
      {page && !rows.length && <Typography color="text.secondary">No hay pacientes con este filtro.</Typography>}

      {page && rows.length > 0 && desktop && (
        <Card>
          <Table size="small" aria-label="Pacientes">
            <TableHead>
              <TableRow>
                <TableCell>Paciente</TableCell>
                <TableCell>Último análisis</TableCell>
                <TableCell>Resultado</TableCell>
                <TableCell>Confianza</TableCell>
                <TableCell>Estado</TableCell>
                <TableCell align="right">Acción</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {rows.map((row) => (
                <TableRow key={row.id} hover>
                  <TableCell>
                    <Stack spacing={0.5}>
                      <span>
                        {row.display_name}
                        {row.age_years != null && ` · ${row.age_years} años`}
                      </span>
                      <HandoverMark row={row} />
                    </Stack>
                  </TableCell>
                  <TableCell>{row.last_analysis ? formatDate(row.last_analysis.created_at) : '—'}</TableCell>
                  <TableCell>
                    <Chip size="small" color={resultColor(row.last_analysis)} label={resultText(row.last_analysis)} />
                  </TableCell>
                  <TableCell>{row.last_analysis ? percent(row.last_analysis.confidence) : '—'}</TableCell>
                  <TableCell>
                    <Chip size="small" color={STATUS[row.status].color} label={STATUS[row.status].label} />
                  </TableCell>
                  <TableCell align="right">
                    <Button size="small" onClick={() => open(row.id)}>
                      Revisar
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Card>
      )}
      {page &&
        !desktop &&
        rows.map((row) => (
          <Card key={row.id}>
            <CardActionArea onClick={() => open(row.id)}>
              <CardContent>
                <Stack direction="row" sx={{ justifyContent: 'space-between', gap: 1, alignItems: 'flex-start' }}>
                  <Box sx={{ minWidth: 0 }}>
                    <Typography variant="subtitle1" component="h2">
                      {row.display_name}
                    </Typography>
                    <Typography variant="body2" color="text.secondary">
                      {row.last_analysis
                        ? `${formatDate(row.last_analysis.created_at)} · confianza ${percent(row.last_analysis.confidence)}`
                        : 'Sin análisis'}
                    </Typography>
                  </Box>
                  <Chip size="small" color={STATUS[row.status].color} label={STATUS[row.status].label} />
                </Stack>
                <Stack direction="row" sx={{ gap: 1, mt: 1, flexWrap: 'wrap' }}>
                  <Chip size="small" color={resultColor(row.last_analysis)} label={resultText(row.last_analysis)} />
                  <HandoverMark row={row} />
                </Stack>
              </CardContent>
            </CardActionArea>
          </Card>
        ))}

      {page && page.total > PAGE && (
        <Stack direction="row" sx={{ justifyContent: 'space-between', alignItems: 'center' }}>
          <Typography variant="body2" color="text.secondary">
            Mostrando {offset + 1}–{Math.min(offset + PAGE, page.total)} de {page.total} pacientes
          </Typography>
          <Stack direction="row" spacing={1}>
            <Button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>
              Anterior
            </Button>
            <Button disabled={offset + PAGE >= page.total} onClick={() => setOffset(offset + PAGE)}>
              Siguiente
            </Button>
          </Stack>
        </Stack>
      )}
      <Typography variant="caption" color="text.secondary" component="p">
        {DISCLAIMER}
      </Typography>
    </Stack>
  );
}
