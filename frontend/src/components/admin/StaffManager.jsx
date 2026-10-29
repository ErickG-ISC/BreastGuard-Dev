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
  InputLabel,
  Menu,
  MenuItem,
  Select,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TextField,
  Typography,
  useMediaQuery,
} from '@mui/material';
import { useCallback, useEffect, useRef, useState } from 'react';
import { api, errorMessage } from '../../api/client';
import { useAuth } from '../../auth/AuthContext';
import { ROLE_LABELS, STATUS_LABELS, emailNotice, formatDateTime } from '../../pages/admin/adminLabels';

function InviteDialog({ open, onClose, onSubmit }) {
  const [form, setForm] = useState({ email: '', full_name: '', role: 'doctor' });
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);
  const set = (field) => (event) => setForm({ ...form, [field]: event.target.value });

  async function submit(event) {
    event.preventDefault();
    setSaving(true);
    setError('');
    try {
      await onSubmit(form);
      setForm({ email: '', full_name: '', role: 'doctor' });
    } catch (err) {
      setError(errorMessage(err, 'No se pudo invitar.'));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open={open} onClose={onClose} fullWidth maxWidth="sm">
      <form onSubmit={submit}>
        <DialogTitle>Invitar a una persona</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 1 }}>
            {error && <Alert severity="error">{error}</Alert>}
            <TextField label="Nombre completo" value={form.full_name} onChange={set('full_name')} required />
            <TextField label="Correo" type="email" value={form.email} onChange={set('email')} required />
            <FormControl>
              <InputLabel id="rol-invitar">Rol</InputLabel>
              <Select labelId="rol-invitar" label="Rol" value={form.role} onChange={set('role')}>
                <MenuItem value="doctor">{ROLE_LABELS.doctor}</MenuItem>
                <MenuItem value="tenant_admin">{ROLE_LABELS.tenant_admin}</MenuItem>
              </Select>
            </FormControl>
            <Typography variant="body2" color="text.secondary">
              Recibirá un enlace de un solo uso para elegir su contraseña. Nadie más la conoce.
            </Typography>
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={onClose}>Cancelar</Button>
          <Button type="submit" variant="contained" disabled={saving}>
            Enviar invitación
          </Button>
        </DialogActions>
      </form>
    </Dialog>
  );
}

function ConfirmDialog({ confirm, onClose }) {
  return (
    <Dialog open={Boolean(confirm)} onClose={onClose}>
      <DialogTitle>{confirm?.title}</DialogTitle>
      <DialogContent>
        <DialogContentText>{confirm?.text}</DialogContentText>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancelar</Button>
        <Button
          variant="contained"
          color={confirm?.danger ? 'error' : 'primary'}
          onClick={() => {
            confirm.run();
            onClose();
          }}
        >
          {confirm?.action}
        </Button>
      </DialogActions>
    </Dialog>
  );
}

function StatusChip({ status }) {
  const meta = STATUS_LABELS[status];
  return <Chip size="small" color={meta.color} label={meta.label} />;
}

function Actions({ user, isSelf, onAction, busy }) {
  const [anchor, setAnchor] = useState(null);
  const options = [];
  if (user.status === 'invited') options.push(['resend', 'Reenviar invitación']);
  if (user.status === 'active' && !isSelf) options.push(['reset', 'Restablecer acceso']);
  if (!isSelf) {
    options.push(['role', user.role === 'doctor' ? 'Hacer administración' : 'Cambiar a médico/a']);
    options.push(user.is_active ? ['deactivate', 'Desactivar'] : ['activate', 'Reactivar']);
  }
  if (!options.length) return <Typography variant="caption">Tú</Typography>;
  return (
    <>
      <Button
        size="small"
        disabled={busy}
        onClick={(e) => setAnchor(e.currentTarget)}
        aria-label={`Acciones para ${user.full_name}`}
      >
        Acciones
      </Button>
      <Menu anchorEl={anchor} open={Boolean(anchor)} onClose={() => setAnchor(null)}>
        {options.map(([key, label]) => (
          <MenuItem
            key={key}
            onClick={() => {
              setAnchor(null);
              onAction(key, user);
            }}
          >
            {label}
          </MenuItem>
        ))}
      </Menu>
    </>
  );
}

// Personal de un tenant con alta por invitación (ADR 0008). Lo usan el platform_admin
// (`/admin/...`) y el tenant_admin (`/institution/...`): cambian solo las URLs.
export default function StaffManager({ listUrl, inviteUrl, userUrl, disabled = false }) {
  const { user: me } = useAuth();
  const desktop = useMediaQuery((theme) => theme.breakpoints.up('md'));
  const [data, setData] = useState(null);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState(null);
  const [inviting, setInviting] = useState(false);
  const [confirm, setConfirm] = useState(null);
  // Una acción a la vez: evita reenvíos dobles por doble clic
  const [busy, setBusy] = useState(false);
  const busyRef = useRef(false);

  const load = useCallback(() => {
    api
      .get(listUrl)
      .then(({ data: body }) => {
        setData(body);
        setError('');
      })
      .catch((err) => setError(errorMessage(err, 'No se pudo cargar el personal.')));
  }, [listUrl]);

  useEffect(() => {
    load();
  }, [load]);

  async function call(request, success) {
    if (busyRef.current) return;
    busyRef.current = true;
    setBusy(true);
    try {
      const { data: body } = await request();
      setNotice({ severity: body?.email_sent === false ? 'warning' : 'success', text: success(body) });
      load();
    } catch (err) {
      setNotice({ severity: 'error', text: errorMessage(err) });
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  }

  function onAction(key, user) {
    const base = userUrl(user.id);
    if (key === 'resend') {
      call(() => api.post(`${base}/invitation`), (body) => emailNotice(body.email_sent));
    } else if (key === 'reset') {
      setConfirm({
        title: `¿Restablecer el acceso de ${user.full_name}?`,
        text: 'Su contraseña deja de servir y se cierran sus sesiones abiertas. Recibirá un enlace para elegir otra.',
        action: 'Restablecer',
        danger: true,
        run: () => call(() => api.post(`${base}/reset-access`), (body) => emailNotice(body.email_sent)),
      });
    } else if (key === 'role') {
      const role = user.role === 'doctor' ? 'tenant_admin' : 'doctor';
      setConfirm({
        title: `¿Cambiar el rol de ${user.full_name}?`,
        text: `Pasará a ${ROLE_LABELS[role]}. Su sesión actual se cerrará.`,
        action: 'Cambiar rol',
        run: () => call(() => api.patch(base, { role }), () => 'Rol actualizado.'),
      });
    } else if (key === 'deactivate') {
      setConfirm({
        title: `¿Desactivar a ${user.full_name}?`,
        text: 'Pierde el acceso de inmediato, incluso si tiene la sesión abierta.',
        action: 'Desactivar',
        danger: true,
        run: () => call(() => api.patch(base, { is_active: false }), () => 'Usuario desactivado.'),
      });
    } else if (key === 'activate') {
      call(() => api.patch(base, { is_active: true }), () => 'Usuario reactivado.');
    }
  }

  async function invite(form) {
    const { data: body } = await api.post(inviteUrl, form);
    setInviting(false);
    setNotice({ severity: body.email_sent ? 'success' : 'warning', text: emailNotice(body.email_sent) });
    load();
  }

  const rows = data?.items ?? [];

  return (
    <Stack spacing={2}>
      <Stack direction="row" sx={{ alignItems: 'center', justifyContent: 'space-between', gap: 1, flexWrap: 'wrap' }}>
        <Typography variant="body2" color="text.secondary">
          {data ? `${rows.length} personas del equipo · ${data.patients} pacientes (solo el conteo)` : ' '}
        </Typography>
        <Button variant="contained" onClick={() => setInviting(true)} disabled={disabled}>
          Invitar
        </Button>
      </Stack>
      {notice && (
        <Alert severity={notice.severity} onClose={() => setNotice(null)}>
          {notice.text}
        </Alert>
      )}
      {error && <Alert severity="error">{error}</Alert>}
      {!data && !error && <CircularProgress sx={{ alignSelf: 'center' }} />}
      {data && desktop && (
        <Card>
          <Table size="small" aria-label="Personal">
            <TableHead>
              <TableRow>
                <TableCell>Nombre</TableCell>
                <TableCell>Correo</TableCell>
                <TableCell>Rol</TableCell>
                <TableCell>Estado</TableCell>
                <TableCell>Último acceso</TableCell>
                <TableCell align="right">Acción</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {rows.map((user) => (
                <TableRow key={user.id}>
                  <TableCell>{user.full_name}</TableCell>
                  <TableCell sx={{ wordBreak: 'break-all' }}>{user.email}</TableCell>
                  <TableCell>{ROLE_LABELS[user.role]}</TableCell>
                  <TableCell>
                    <StatusChip status={user.status} />
                  </TableCell>
                  <TableCell>{formatDateTime(user.last_login_at)}</TableCell>
                  <TableCell align="right">
                    <Actions user={user} isSelf={user.id === me?.user_id} onAction={onAction} busy={busy} />
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Card>
      )}
      {data &&
        !desktop &&
        rows.map((user) => (
          <Card key={user.id}>
            <CardContent>
              <Stack direction="row" sx={{ justifyContent: 'space-between', alignItems: 'flex-start', gap: 1 }}>
                <Box sx={{ minWidth: 0 }}>
                  <Typography variant="subtitle1" component="h3">
                    {user.full_name}
                  </Typography>
                  <Typography variant="body2" color="text.secondary" sx={{ wordBreak: 'break-all' }}>
                    {user.email}
                  </Typography>
                  <Typography variant="body2" color="text.secondary">
                    {ROLE_LABELS[user.role]} · último acceso {formatDateTime(user.last_login_at)}
                  </Typography>
                </Box>
                <StatusChip status={user.status} />
              </Stack>
              <Box sx={{ mt: 1, textAlign: 'right' }}>
                <Actions user={user} isSelf={user.id === me?.user_id} onAction={onAction} busy={busy} />
              </Box>
            </CardContent>
          </Card>
        ))}
      <InviteDialog open={inviting} onClose={() => setInviting(false)} onSubmit={invite} />
      <ConfirmDialog confirm={confirm} onClose={() => setConfirm(null)} />
    </Stack>
  );
}
