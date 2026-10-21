import {
  Alert,
  Box,
  Button,
  Card,
  CardActions,
  CardContent,
  Chip,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControlLabel,
  List,
  ListItem,
  ListItemText,
  Stack,
  Switch,
  TextField,
  Typography,
} from '@mui/material';
import { useCallback, useEffect, useState } from 'react';
import { api, errorMessage } from '../../api/client';
import Layout from '../../components/Layout';

const EMPTY_FORM = {
  name: '',
  slug: '',
  plan: 'basic',
  admin_email: '',
  admin_full_name: '',
  admin_password: '',
};

function CreateTenantDialog({ open, onClose, onCreated }) {
  const [form, setForm] = useState(EMPTY_FORM);
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);

  const update = (field) => (event) => setForm({ ...form, [field]: event.target.value });

  async function handleSubmit(event) {
    event.preventDefault();
    setError('');
    setSaving(true);
    try {
      const { data } = await api.post('/admin/tenants', form);
      setForm(EMPTY_FORM);
      onCreated(data.tenant);
    } catch (err) {
      setError(errorMessage(err, 'No se pudo crear el tenant.'));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open={open} onClose={onClose} fullWidth maxWidth="sm">
      <form onSubmit={handleSubmit}>
        <DialogTitle>Nueva institución</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 1 }}>
            {error && <Alert severity="error">{error}</Alert>}
            <TextField label="Nombre" value={form.name} onChange={update('name')} required />
            <TextField
              label="Slug"
              value={form.slug}
              onChange={update('slug')}
              helperText="Minúsculas, números y guiones. No se puede cambiar después."
              required
            />
            <TextField label="Plan" value={form.plan} onChange={update('plan')} required />
            <Typography variant="subtitle2">Primer administrador de la institución</Typography>
            <TextField
              label="Email"
              type="email"
              value={form.admin_email}
              onChange={update('admin_email')}
              required
            />
            <TextField
              label="Nombre completo"
              value={form.admin_full_name}
              onChange={update('admin_full_name')}
              required
            />
            <TextField
              label="Contraseña inicial"
              type="password"
              autoComplete="new-password"
              value={form.admin_password}
              onChange={update('admin_password')}
              helperText="Al menos 12 caracteres."
              required
            />
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={onClose}>Cancelar</Button>
          <Button type="submit" variant="contained" disabled={saving}>
            {saving ? 'Creando…' : 'Crear'}
          </Button>
        </DialogActions>
      </form>
    </Dialog>
  );
}

const CHECKS = [
  ['app_role_without_bypass', 'La app se conecta sin superusuario ni BYPASSRLS', (r) => r.app_role_without_bypass],
  ['rows_visible_without_context', 'Sin contexto de tenant se ven 0 filas', (r) => r.rows_visible_without_context === 0],
  ['foreign_rows_visible_to_tenant', 'El tenant ve 0 filas de otros tenants', (r) => r.foreign_rows_visible_to_tenant === 0],
  ['tenant_rows_visible_to_others', 'Los demás tenants ven 0 filas de este', (r) => r.tenant_rows_visible_to_others === 0],
  ['conclusive', 'Prueba concluyente (hay filas testigo y otros tenants)', (r) => r.conclusive],
];

function IsolationDialog({ tenant, onClose }) {
  const [report, setReport] = useState(null);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!tenant) return;
    api
      .post(`/admin/tenants/${tenant.id}/isolation-check`)
      .then(({ data }) => setReport(data))
      .catch((err) => setError(errorMessage(err, 'No se pudo ejecutar el chequeo.')));
  }, [tenant]);

  return (
    <Dialog open={Boolean(tenant)} onClose={onClose} fullWidth maxWidth="sm">
      <DialogTitle>Chequeo de aislamiento: {tenant?.slug}</DialogTitle>
      <DialogContent>
        {error && <Alert severity="error">{error}</Alert>}
        {!report && !error && (
          <Box sx={{ display: 'flex', justifyContent: 'center', py: 3 }}>
            <CircularProgress />
          </Box>
        )}
        {report && (
          <Stack spacing={2}>
            <Alert severity={report.passed ? 'success' : 'error'}>
              {report.passed ? 'Aislamiento verificado' : 'El chequeo NO pasó'}
            </Alert>
            <List dense>
              {CHECKS.map(([key, label, ok]) => (
                <ListItem key={key} disableGutters>
                  <ListItemText primary={label} />
                  <Chip size="small" color={ok(report) ? 'success' : 'error'} label={ok(report) ? 'OK' : 'Falla'} />
                </ListItem>
              ))}
            </List>
            <Typography variant="body2" color="text.secondary">
              Tenants comparados: {report.other_tenants_checked}. Tablas revisadas:{' '}
              {report.tables_checked.join(', ')}. Se ejecuta como el rol de la app en una
              transacción de solo lectura y solo devuelve conteos.
            </Typography>
          </Stack>
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cerrar</Button>
      </DialogActions>
    </Dialog>
  );
}

export default function Tenants() {
  const [tenants, setTenants] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [creating, setCreating] = useState(false);
  const [checking, setChecking] = useState(null);

  const load = useCallback(async () => {
    try {
      const { data } = await api.get('/admin/tenants');
      setTenants(data);
      setError('');
    } catch (err) {
      setError(errorMessage(err, 'No se pudieron cargar los tenants.'));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function toggleActive(tenant) {
    try {
      await api.patch(`/admin/tenants/${tenant.id}`, { is_active: !tenant.is_active });
      await load();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  return (
    <Layout>
      <Stack direction="row" sx={{ alignItems: 'center', justifyContent: 'space-between', mb: 2, gap: 1, flexWrap: 'wrap' }}>
        <Typography variant="h5" component="h1">
          Tenants
        </Typography>
        <Button variant="contained" onClick={() => setCreating(true)}>
          Nueva institución
        </Button>
      </Stack>
      {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
      {loading ? (
        <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
          <CircularProgress />
        </Box>
      ) : (
        <Stack spacing={2}>
          {tenants.map((tenant) => (
            <Card key={tenant.id} variant="outlined">
              <CardContent>
                <Stack direction="row" sx={{ alignItems: 'center', gap: 1, flexWrap: 'wrap' }}>
                  <Typography variant="h6" component="h2">
                    {tenant.name}
                  </Typography>
                  <Chip size="small" label={tenant.kind === 'b2c' ? 'B2C compartido' : 'Institución'} />
                  {!tenant.is_active && <Chip size="small" color="warning" label="Inactivo" />}
                </Stack>
                <Typography variant="body2" color="text.secondary" sx={{ wordBreak: 'break-all' }}>
                  {tenant.slug} · plan {tenant.plan}
                </Typography>
              </CardContent>
              <CardActions sx={{ flexWrap: 'wrap', gap: 1, px: 2, pb: 2 }}>
                <Button size="small" variant="outlined" onClick={() => setChecking(tenant)}>
                  Chequeo de aislamiento
                </Button>
                {tenant.kind !== 'b2c' && (
                  <FormControlLabel
                    control={<Switch checked={tenant.is_active} onChange={() => toggleActive(tenant)} />}
                    label="Activo"
                  />
                )}
              </CardActions>
            </Card>
          ))}
        </Stack>
      )}
      <CreateTenantDialog
        open={creating}
        onClose={() => setCreating(false)}
        onCreated={(tenant) => {
          setCreating(false);
          load();
          setChecking(tenant);
        }}
      />
      {/* key: un diálogo nuevo por tenant, sin estado del chequeo anterior */}
      <IsolationDialog key={checking?.id ?? 'none'} tenant={checking} onClose={() => setChecking(null)} />
    </Layout>
  );
}
