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
  FormControl,
  InputLabel,
  List,
  ListItem,
  ListItemText,
  MenuItem,
  Select,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TextField,
  ToggleButton,
  ToggleButtonGroup,
  Typography,
  useMediaQuery,
} from '@mui/material';
import { useEffect, useState } from 'react';
import { Link as RouterLink, useNavigate } from 'react-router-dom';
import { api, errorMessage } from '../../api/client';
import IsolationDialog from '../../components/admin/IsolationDialog';
import { PLAN_LABELS, emailNotice, formatDateTime } from './adminLabels';

const PAGE = 20;
const EMPTY_FORM = { name: '', slug: '', plan: 'basic', admin_email: '', admin_full_name: '' };

function CreateTenantDialog({ open, onClose, onCreated }) {
  const [form, setForm] = useState(EMPTY_FORM);
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);
  const set = (field) => (event) => setForm({ ...form, [field]: event.target.value });

  async function submit(event) {
    event.preventDefault();
    setError('');
    setSaving(true);
    try {
      const { data } = await api.post('/admin/tenants', form);
      setForm(EMPTY_FORM);
      onCreated(data);
    } catch (err) {
      setError(errorMessage(err, 'No se pudo crear la institución.'));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open={open} onClose={onClose} fullWidth maxWidth="sm">
      <form onSubmit={submit}>
        <DialogTitle>Alta de tenant</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 1 }}>
            {error && <Alert severity="error">{error}</Alert>}
            <TextField label="Nombre de la institución" value={form.name} onChange={set('name')} required />
            <TextField
              label="Identificador (slug)"
              value={form.slug}
              onChange={set('slug')}
              helperText="Minúsculas, números y guiones; por ejemplo clinica-ejemplo. No se puede cambiar."
              required
            />
            <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2}>
              <TextField label="Tipo" value="Institución" disabled fullWidth helperText="Fijo" />
              <FormControl fullWidth>
                <InputLabel id="plan-alta">Plan (simulado)</InputLabel>
                <Select labelId="plan-alta" label="Plan (simulado)" value={form.plan} onChange={set('plan')}>
                  {Object.entries(PLAN_LABELS).map(([code, label]) => (
                    <MenuItem key={code} value={code}>
                      {label}
                    </MenuItem>
                  ))}
                </Select>
              </FormControl>
            </Stack>
            <Typography variant="subtitle2">Primer administrador</Typography>
            <TextField
              label="Nombre completo"
              value={form.admin_full_name}
              onChange={set('admin_full_name')}
              required
            />
            <TextField
              label="Correo del primer administrador"
              type="email"
              value={form.admin_email}
              onChange={set('admin_email')}
              helperText="Recibirá un enlace de un solo uso para elegir su contraseña."
              required
            />
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={onClose}>Cancelar</Button>
          <Button type="submit" variant="contained" disabled={saving}>
            {saving ? 'Creando…' : 'Crear tenant'}
          </Button>
        </DialogActions>
      </form>
    </Dialog>
  );
}

function CreatedResult({ result, onCheck, onClose }) {
  return (
    <Alert severity="success" onClose={onClose}>
      <Typography variant="subtitle2">Resultado del alta: {result.tenant.name}</Typography>
      <List dense disablePadding>
        <ListItem disableGutters>
          <ListItemText primary="Tenant registrado" />
        </ListItem>
        <ListItem disableGutters>
          <ListItemText primary="Administrador invitado" secondary={emailNotice(result.email_sent)} />
        </ListItem>
        <ListItem disableGutters>
          <ListItemText primary="Bitácora registrada" />
        </ListItem>
      </List>
      <Button size="small" variant="outlined" onClick={onCheck}>
        Ver chequeo de aislamiento
      </Button>
    </Alert>
  );
}

function StateChip({ tenant }) {
  if (tenant.purge_requested_at) return <Chip size="small" color="error" label="Purga pendiente" />;
  return tenant.is_active ? (
    <Chip size="small" color="success" label="Activo" />
  ) : (
    <Chip size="small" label="Inactivo" />
  );
}

export default function Tenants() {
  const desktop = useMediaQuery((theme) => theme.breakpoints.up('md'));
  const navigate = useNavigate();
  const [query, setQuery] = useState('');
  const [active, setActive] = useState('all');
  const [offset, setOffset] = useState(0);
  const [page, setPage] = useState(null);
  const [error, setError] = useState('');
  const [creating, setCreating] = useState(false);
  const [created, setCreated] = useState(null);
  const [checking, setChecking] = useState(null);
  const [reload, setReload] = useState(0);

  useEffect(() => {
    const params = { limit: PAGE, offset };
    if (query.trim()) params.q = query.trim();
    if (active !== 'all') params.active = active === 'active';
    api
      .get('/admin/tenants', { params })
      .then(({ data }) => {
        setPage(data);
        setError('');
      })
      .catch((err) => setError(errorMessage(err, 'No se pudieron cargar los tenants.')));
  }, [query, active, offset, reload]);

  const items = page?.items ?? [];
  const kindLabel = (t) => (t.kind === 'b2c' ? 'Compartido' : 'Institución');

  return (
    <Stack spacing={2}>
      <Stack direction="row" sx={{ alignItems: 'center', justifyContent: 'space-between', gap: 1, flexWrap: 'wrap' }}>
        <Typography variant="h5" component="h1">
          Tenants
        </Typography>
        <Button variant="contained" onClick={() => setCreating(true)}>
          Alta de tenant
        </Button>
      </Stack>
      {created && (
        <CreatedResult
          result={created}
          onCheck={() => setChecking(created.tenant)}
          onClose={() => setCreated(null)}
        />
      )}
      <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2}>
        <TextField
          size="small"
          placeholder="Buscar por nombre o identificador…"
          value={query}
          onChange={(e) => {
            setOffset(0);
            setQuery(e.target.value);
          }}
          slotProps={{ htmlInput: { 'aria-label': 'Buscar tenants' } }}
          sx={{ maxWidth: { sm: 360 } }}
        />
        <ToggleButtonGroup
          exclusive
          size="small"
          value={active}
          onChange={(_, value) => {
            if (!value) return;
            setOffset(0);
            setActive(value);
          }}
          aria-label="Estado"
        >
          <ToggleButton value="all">Todos</ToggleButton>
          <ToggleButton value="active">Activos</ToggleButton>
          <ToggleButton value="inactive">Inactivos</ToggleButton>
        </ToggleButtonGroup>
      </Stack>
      {error && <Alert severity="error">{error}</Alert>}
      {!page && !error && <CircularProgress sx={{ alignSelf: 'center' }} />}
      {page && items.length === 0 && (
        <Typography variant="body2" color="text.secondary">
          Ningún tenant coincide.
        </Typography>
      )}
      {page && items.length > 0 && desktop && (
        <Card>
          <Table aria-label="Tenants">
            <TableHead>
              <TableRow>
                <TableCell>Institución</TableCell>
                <TableCell>Identificador</TableCell>
                <TableCell>Tipo</TableCell>
                <TableCell>Estado</TableCell>
                <TableCell align="right">Equipo</TableCell>
                <TableCell align="right">Pacientes</TableCell>
                <TableCell>Último acceso</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {items.map((tenant) => (
                <TableRow
                  key={tenant.id}
                  hover
                  sx={{ cursor: 'pointer' }}
                  onClick={() => navigate(`/admin/tenants/${tenant.id}`)}
                >
                  <TableCell>
                    <RouterLink to={`/admin/tenants/${tenant.id}`} onClick={(e) => e.stopPropagation()}>
                      {tenant.name}
                    </RouterLink>
                  </TableCell>
                  <TableCell>{tenant.slug}</TableCell>
                  <TableCell>{kindLabel(tenant)}</TableCell>
                  <TableCell>
                    <StateChip tenant={tenant} />
                  </TableCell>
                  <TableCell align="right">{tenant.stats.staff}</TableCell>
                  <TableCell align="right">{tenant.stats.patients}</TableCell>
                  <TableCell>{formatDateTime(tenant.stats.last_login_at)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Card>
      )}
      {page &&
        !desktop &&
        items.map((tenant) => (
          <Card key={tenant.id}>
            <CardActionArea component={RouterLink} to={`/admin/tenants/${tenant.id}`}>
              <CardContent>
                <Stack direction="row" sx={{ justifyContent: 'space-between', gap: 1 }}>
                  <Box sx={{ minWidth: 0 }}>
                    <Typography variant="subtitle1" component="h2">
                      {tenant.name}
                    </Typography>
                    <Typography variant="body2" color="text.secondary" sx={{ wordBreak: 'break-all' }}>
                      {tenant.slug} · {kindLabel(tenant)}
                    </Typography>
                    <Typography variant="body2" color="text.secondary">
                      {tenant.stats.staff} del equipo · {tenant.stats.patients} pacientes
                    </Typography>
                  </Box>
                  <StateChip tenant={tenant} />
                </Stack>
              </CardContent>
            </CardActionArea>
          </Card>
        ))}
      {page && page.total > PAGE && (
        <Stack direction="row" sx={{ justifyContent: 'space-between', alignItems: 'center' }}>
          <Typography variant="body2" color="text.secondary">
            Mostrando {offset + 1}–{Math.min(offset + PAGE, page.total)} de {page.total}
          </Typography>
          <Stack direction="row" spacing={1}>
            <Button disabled={offset === 0} onClick={() => setOffset(offset - PAGE)}>
              Anterior
            </Button>
            <Button disabled={offset + PAGE >= page.total} onClick={() => setOffset(offset + PAGE)}>
              Siguiente
            </Button>
          </Stack>
        </Stack>
      )}
      <CreateTenantDialog
        open={creating}
        onClose={() => setCreating(false)}
        onCreated={(result) => {
          setCreating(false);
          setCreated(result);
          setChecking(result.tenant);
          setReload((n) => n + 1);
        }}
      />
      <IsolationDialog key={checking?.id ?? 'none'} tenant={checking} onClose={() => setChecking(null)} />
    </Stack>
  );
}
