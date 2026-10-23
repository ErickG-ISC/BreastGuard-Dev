import { Alert, Button, Paper, Stack, Typography } from '@mui/material';
import { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { api, errorMessage } from '../api/client';
import Layout from '../components/Layout';

// Baja de un recordatorio por correo (enlace del correo, sin iniciar sesión). Se confirma con un
// botón: abrir el enlace no basta, así los escáneres de correo no dan de baja a nadie.
export default function Unsubscribe() {
  const [params] = useSearchParams();
  // El token se guarda en memoria y se quita de la barra de direcciones (historial, capturas)
  const [token] = useState(() => params.get('token'));
  useEffect(() => {
    if (window.location.search) window.history.replaceState(null, '', window.location.pathname);
  }, []);
  const [state, setState] = useState('idle');
  const [error, setError] = useState('');

  async function confirm() {
    setState('sending');
    try {
      await api.post('/reminders/unsubscribe', { token });
      setState('done');
    } catch (err) {
      setError(errorMessage(err, 'No se pudo completar la baja.'));
      setState('idle');
    }
  }

  return (
    <Layout>
      <Paper sx={{ p: 3 }}>
        <Stack spacing={2}>
          <Typography variant="h5" component="h1">
            Dejar de recibir este recordatorio por correo
          </Typography>
          {!token && <Alert severity="error">El enlace está incompleto.</Alert>}
          {state === 'done' ? (
            <Alert severity="success">
              Listo. Ya no recibirás este recordatorio por correo; lo seguirás viendo dentro de la app. Puedes cambiarlo
              cuando quieras en Recordatorios.
            </Alert>
          ) : (
            token && (
              <Button variant="contained" onClick={confirm} disabled={state === 'sending'} sx={{ alignSelf: 'start' }}>
                Confirmar
              </Button>
            )
          )}
          {error && <Alert severity="error">{error}</Alert>}
        </Stack>
      </Paper>
    </Layout>
  );
}
