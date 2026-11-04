import { Alert, Button, Card, CardContent, CircularProgress, Stack, Typography } from '@mui/material';
import { useCallback, useEffect, useRef, useState } from 'react';
import { Navigate, Link as RouterLink } from 'react-router-dom';
import { api, errorMessage } from '../../api/client';
import { formatDateTime } from '../admin/adminLabels';
import { PENDING_CODE_KEY } from '../ImportLink';

function hasPendingCode() {
  try {
    return Boolean(sessionStorage.getItem(PENDING_CODE_KEY));
  } catch {
    return false;
  }
}

// Inicio de la médica. Por ahora, los traspasos de pacientes hacia ella (0014); el panel con
// la lista de pacientes llega con CU-11.
export default function DoctorHome() {
  const [items, setItems] = useState(null);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const busyRef = useRef(false);
  const [notices, setNotices] = useState([]);
  // Llegó por el enlace de la paciente antes de iniciar sesión: directo a importar
  const [pending] = useState(hasPendingCode);

  const load = useCallback(() => {
    api
      .get('/doctor/handovers')
      .then(({ data }) => {
        setItems(data);
        setError('');
      })
      .catch((err) => setError(errorMessage(err, 'No se pudieron cargar los traspasos.')));
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
      setNotice(`Ahora eres la médica responsable de ${data.patients_moved} pacientes de ${item.from_name}.`);
      load();
    } catch (err) {
      setError(errorMessage(err, 'No se pudo aceptar el traspaso.'));
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  }

  if (pending) return <Navigate to="/medico/importar" replace />;

  return (
    <Stack spacing={2}>
      <Typography variant="h5" component="h1">
        Inicio
      </Typography>
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
      {notice && (
        <Alert severity="success" onClose={() => setNotice('')}>
          {notice}
        </Alert>
      )}
      {error && <Alert severity="error">{error}</Alert>}
      {!items && !error && <CircularProgress sx={{ alignSelf: 'center' }} />}
      {items && !items.length && (
        <Typography color="text.secondary">No tienes traspasos de pacientes pendientes.</Typography>
      )}
      {items?.map((item) => (
        <Card key={item.id}>
          <CardContent>
            <Typography variant="subtitle1" component="h2">
              Pacientes de {item.from_name}
            </Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
              La administración te las traspasó el {formatDateTime(item.created_at)}. Ya puedes verlas;
              al aceptar pasas a ser su médica responsable.
            </Typography>
            <Button variant="contained" disabled={busy} onClick={() => accept(item)}>
              Aceptar traspaso
            </Button>
          </CardContent>
        </Card>
      ))}
    </Stack>
  );
}
