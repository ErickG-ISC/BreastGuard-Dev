import { Alert, Button, CircularProgress, Paper, Stack, TextField, Typography } from '@mui/material';
import { useEffect, useState } from 'react';
import { Link as RouterLink } from 'react-router-dom';
import { api, errorMessage } from '../api/client';
import Layout from '../components/Layout';

const MIN_LENGTH = 12;

// Lee el token del fragmento (#token=…): nunca viaja al servidor en la URL ni queda en el
// historial (se quita de la barra en cuanto se lee).
function readToken() {
  const params = new URLSearchParams(window.location.hash.replace(/^#/, ''));
  return params.get('token');
}

export default function AcceptInvitation() {
  const [token] = useState(readToken);
  const [info, setInfo] = useState(null);
  const [error, setError] = useState(token ? '' : 'El enlace está incompleto.');
  const [password, setPassword] = useState('');
  const [repeat, setRepeat] = useState('');
  const [saving, setSaving] = useState(false);
  const [done, setDone] = useState(false);

  useEffect(() => {
    if (window.location.hash) window.history.replaceState(null, '', window.location.pathname);
    if (!token) return;
    api
      .post('/auth/invitations/inspect', { token })
      .then(({ data }) => setInfo(data))
      .catch((err) => setError(errorMessage(err, 'El enlace no es válido.')));
  }, [token]);

  async function submit(event) {
    event.preventDefault();
    setSaving(true);
    setError('');
    try {
      await api.post('/auth/invitations/accept', { token, password });
      setDone(true);
    } catch (err) {
      setError(errorMessage(err, 'No se pudo guardar la contraseña.'));
    } finally {
      setSaving(false);
    }
  }

  const mismatch = repeat.length > 0 && repeat !== password;
  const ready = password.length >= MIN_LENGTH && password === repeat;

  return (
    <Layout>
      <Paper sx={{ p: 3, maxWidth: 480, mx: 'auto' }}>
        <Stack spacing={2}>
          <Typography variant="h5" component="h1">
            {info?.purpose === 'reset' ? 'Restablece tu acceso' : 'Activa tu cuenta'}
          </Typography>
          {!info && !error && <CircularProgress sx={{ alignSelf: 'center' }} />}
          {error && <Alert severity="error">{error}</Alert>}
          {done ? (
            <>
              <Alert severity="success">Listo. Ya puedes iniciar sesión con tu nueva contraseña.</Alert>
              <Button component={RouterLink} to="/login" variant="contained">
                Iniciar sesión
              </Button>
            </>
          ) : (
            info && (
              <Stack spacing={2} component="form" onSubmit={submit}>
                <Typography variant="body2">
                  {info.full_name} · {info.institution}
                  <br />
                  Cuenta: {info.email_masked}
                </Typography>
                <TextField
                  label="Contraseña nueva"
                  type="password"
                  autoComplete="new-password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  helperText={`Al menos ${MIN_LENGTH} caracteres. Solo tú la conocerás.`}
                  required
                />
                <TextField
                  label="Repite la contraseña"
                  type="password"
                  autoComplete="new-password"
                  value={repeat}
                  onChange={(e) => setRepeat(e.target.value)}
                  error={mismatch}
                  helperText={mismatch ? 'No coincide' : ' '}
                  required
                />
                <Button type="submit" variant="contained" disabled={!ready || saving}>
                  Guardar contraseña
                </Button>
              </Stack>
            )
          )}
        </Stack>
      </Paper>
    </Layout>
  );
}
