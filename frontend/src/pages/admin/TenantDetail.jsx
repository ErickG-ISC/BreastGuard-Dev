import {
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
  DialogContentText,
  DialogTitle,
  FormControl,
  Grid,
  InputLabel,
  MenuItem,
  Select,
  Stack,
  TextField,
  Typography,
} from '@mui/material';
import { useCallback, useEffect, useState } from 'react';
import { Link as RouterLink, useParams } from 'react-router-dom';
import { api, errorMessage } from '../../api/client';
import EventsLog from '../../components/admin/EventsLog';
import IsolationDialog from '../../components/admin/IsolationDialog';
import StaffManager from '../../components/admin/StaffManager';
import { PLAN_LABELS, formatDateTime } from './adminLabels';

function Stat({ label, value }) {
  return (
    <Card>
      <CardContent>
        <Typography variant="caption" color="text.secondary">
          {label}
        </Typography>
        <Typography variant="h6" component="p">
          {value}
        </Typography>
      </CardContent>
    </Card>
  );
}

function EditForm({ tenant, onSaved }) {
  const [form, setForm] = useState({ name: tenant.name, plan: tenant.plan });
  const [message, setMessage] = useState(null);

  async function save(event) {
    event.preventDefault();
    const changes = {};
    if (form.name !== tenant.name) changes.name = form.name;
    if (form.plan !== tenant.plan) changes.plan = form.plan;
    if (!Object.keys(changes).length) return;
    try {
      const { data } = await api.patch(`/admin/tenants/${tenant.id}`, changes);
      setMessage({ severity: 'success', text: 'Cambios guardados.' });
      onSaved(data);
    } catch (err) {
      setMessage({ severity: 'error', text: errorMessage(err) });
    }
  }

  return (
    <Card>
      <CardContent>
        <Stack spacing={2} component="form" onSubmit={save}>
          <Typography variant="h6" component="h2">
            Datos de la institución
          </Typography>
          <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2}>
            <TextField
              label="Nombre"
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              required
            />
            <FormControl fullWidth>
              <InputLabel id="plan-editar">Plan (simulado)</InputLabel>
              <Select
                labelId="plan-editar"
                label="Plan (simulado)"
                value={form.plan}
                onChange={(e) => setForm({ ...form, plan: e.target.value })}
                disabled={tenant.kind === 'b2c'}
              >
                {Object.entries(PLAN_LABELS).map(([code, label]) => (
                  <MenuItem key={code} value={code}>
                    {label}
                  </MenuItem>
                ))}
                {!PLAN_LABELS[tenant.plan] && <MenuItem value={tenant.plan}>{tenant.plan}</MenuItem>}
              </Select>
            </FormControl>
            <TextField label="Tipo" value={tenant.kind === 'b2c' ? 'Compartido (B2C)' : 'Institución'} disabled />
          </Stack>
          {message && <Alert severity={message.severity}>{message.text}</Alert>}
          <Button type="submit" variant="contained" sx={{ alignSelf: 'flex-start' }}>
            Guardar
          </Button>
        </Stack>
      </CardContent>
    </Card>
  );
}

function PurgeDialog({ tenant, open, onClose, onDone }) {
  const [typed, setTyped] = useState('');
  const [error, setError] = useState('');

  async function confirm() {
    try {
      const { data } = await api.post(`/admin/tenants/${tenant.id}/purge-request`, { confirm_slug: typed });
      onDone(data);
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  return (
    <Dialog open={open} onClose={onClose} fullWidth maxWidth="sm">
      <DialogTitle>Solicitar la purga de {tenant.name}</DialogTitle>
      <DialogContent>
        <Stack spacing={2}>
          <DialogContentText>
            La institución se desactiva de inmediato: nadie de ella podrá entrar. El borrado definitivo de sus
            datos y archivos lo ejecuta una persona operadora con <code>purge_tenant.py --pending</code>. Hasta
            entonces puedes cancelar la purga.
          </DialogContentText>
          <TextField
            label={`Escribe "${tenant.slug}" para confirmar`}
            value={typed}
            onChange={(e) => setTyped(e.target.value)}
            autoComplete="off"
          />
          {error && <Alert severity="error">{error}</Alert>}
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancelar</Button>
        <Button color="error" variant="contained" disabled={typed !== tenant.slug} onClick={confirm}>
          Solicitar purga
        </Button>
      </DialogActions>
    </Dialog>
  );
}

function DangerZone({ tenant, onChange }) {
  const [purging, setPurging] = useState(false);
  const [error, setError] = useState('');
  const b2c = tenant.kind === 'b2c';

  async function run(promise) {
    try {
      const { data } = await promise;
      setError('');
      onChange(data);
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  return (
    <Card sx={{ borderColor: 'error.main' }}>
      <CardContent>
        <Stack spacing={2}>
          <Typography variant="h6" component="h2">
            Zona de riesgo
          </Typography>
          {b2c && <Alert severity="info">El tenant B2C compartido no se desactiva ni se purga.</Alert>}
          {tenant.purge_requested_at && (
            <Alert
              severity="warning"
              action={
                <Button color="inherit" size="small" onClick={() => run(api.delete(`/admin/tenants/${tenant.id}/purge-request`))}>
                  Cancelar purga
                </Button>
              }
            >
              Purga solicitada ({formatDateTime(tenant.purge_requested_at)}). La institución ya está
              desactivada: nadie de ella puede entrar. Por seguridad, la app no borra datos clínicos ni la
              auditoría; el borrado definitivo lo ejecuta una persona operadora desde su computadora con{' '}
              <code>python -m backend.scripts.purge_tenant --pending</code>. Hasta entonces la solicitud queda
              pendiente y puedes cancelarla.
            </Alert>
          )}
          {error && <Alert severity="error">{error}</Alert>}
          {!b2c && (
            <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1}>
              <Button
                variant="outlined"
                color={tenant.is_active ? 'error' : 'primary'}
                disabled={Boolean(tenant.purge_requested_at)}
                onClick={() => run(api.patch(`/admin/tenants/${tenant.id}`, { is_active: !tenant.is_active }))}
              >
                {tenant.is_active ? 'Desactivar institución' : 'Reactivar institución'}
              </Button>
              <Button
                variant="contained"
                color="error"
                disabled={Boolean(tenant.purge_requested_at)}
                onClick={() => setPurging(true)}
              >
                Solicitar purga
              </Button>
            </Stack>
          )}
        </Stack>
      </CardContent>
      <PurgeDialog
        tenant={tenant}
        open={purging}
        onClose={() => setPurging(false)}
        onDone={(data) => {
          setPurging(false);
          onChange(data);
        }}
      />
    </Card>
  );
}

export default function TenantDetail() {
  const { id } = useParams();
  const [tenant, setTenant] = useState(null);
  const [error, setError] = useState('');
  const [checking, setChecking] = useState(false);
  const [staffKey, setStaffKey] = useState(0);

  const load = useCallback(() => {
    api
      .get(`/admin/tenants/${id}`)
      .then(({ data }) => setTenant(data))
      .catch((err) => setError(errorMessage(err, 'No se encontró el tenant.')));
  }, [id]);

  useEffect(() => {
    load();
  }, [load]);

  function changed(data) {
    setTenant(data);
    setStaffKey((k) => k + 1);
  }

  if (error) return <Alert severity="error">{error}</Alert>;
  if (!tenant) return <CircularProgress />;

  const stats = tenant.stats;
  return (
    <Stack spacing={3}>
      <Button component={RouterLink} to="/admin/tenants" sx={{ alignSelf: 'flex-start' }}>
        ← Tenants
      </Button>
      <Stack direction="row" sx={{ alignItems: 'center', gap: 1, flexWrap: 'wrap' }}>
        <Typography variant="h5" component="h1">
          {tenant.name}
        </Typography>
        <Chip size="small" label={tenant.slug} />
        {tenant.is_active ? (
          <Chip size="small" color="success" label="Activo" />
        ) : (
          <Chip size="small" label="Inactivo" />
        )}
        <Box sx={{ flexGrow: 1 }} />
        <Button variant="outlined" onClick={() => setChecking(true)}>
          Chequeo de aislamiento
        </Button>
      </Stack>
      <Grid container spacing={2}>
        <Grid size={{ xs: 6, md: 3 }}>
          <Stat label="Equipo" value={`${stats.staff_active} activos de ${stats.staff}`} />
        </Grid>
        <Grid size={{ xs: 6, md: 3 }}>
          <Stat label="Invitaciones pendientes" value={stats.invitations_pending} />
        </Grid>
        <Grid size={{ xs: 6, md: 3 }}>
          <Stat label="Pacientes (conteo)" value={stats.patients} />
        </Grid>
        <Grid size={{ xs: 6, md: 3 }}>
          <Stat label="Último acceso" value={formatDateTime(stats.last_login_at)} />
        </Grid>
      </Grid>
      <EditForm key={`${tenant.name}-${tenant.plan}`} tenant={tenant} onSaved={changed} />
      {tenant.kind !== 'b2c' && (
        <Box>
          <Typography variant="h6" component="h2" sx={{ mb: 1 }}>
            Usuarios
          </Typography>
          <StaffManager
            key={staffKey}
            listUrl={`/admin/tenants/${tenant.id}/users`}
            inviteUrl={`/admin/tenants/${tenant.id}/users`}
            userUrl={(userId) => `/admin/users/${userId}`}
            handoversUrl={`/admin/tenants/${tenant.id}/handovers`}
            handoverUrl={(id) => `/admin/handovers/${id}`}
            disabled={!tenant.is_active}
          />
        </Box>
      )}
      <Box>
        <Typography variant="h6" component="h2" sx={{ mb: 1 }}>
          Bitácora de esta institución
        </Typography>
        <EventsLog key={staffKey} url="/admin/events" fixedTenantId={tenant.id} />
      </Box>
      <DangerZone tenant={tenant} onChange={changed} />
      <IsolationDialog key={checking ? 'on' : 'off'} tenant={checking ? tenant : null} onClose={() => setChecking(false)} />
    </Stack>
  );
}
