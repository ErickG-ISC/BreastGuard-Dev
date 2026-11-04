import { Alert, Button, Card, CardContent, Stack, TextField, Typography } from '@mui/material';
import { useEffect, useRef, useState } from 'react';
import { Link as RouterLink } from 'react-router-dom';
import { api, errorMessage } from '../../api/client';
import { PENDING_CODE_KEY } from '../ImportLink';

function pendingCode() {
  try {
    return sessionStorage.getItem(PENDING_CODE_KEY) ?? '';
  } catch {
    return '';
  }
}

// CU-08: la médica importa el paquete de su paciente como copia en su institución
export default function Import() {
  const [code, setCode] = useState(pendingCode);
  const [result, setResult] = useState(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const busyRef = useRef(false);

  // Ya está en el campo: que no quede guardado ni vuelva a redirigir desde el inicio
  useEffect(() => {
    try {
      sessionStorage.removeItem(PENDING_CODE_KEY);
    } catch {
      // nada que limpiar
    }
  }, []);

  async function submit(event) {
    event.preventDefault();
    if (busyRef.current) return;
    busyRef.current = true;
    setBusy(true);
    setError('');
    try {
      const { data } = await api.post('/doctor/shares/import', { code });
      setResult(data);
      setCode('');
    } catch (err) {
      setError(errorMessage(err, 'No se pudo importar el paquete.'));
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  }

  return (
    <Stack spacing={2}>
      <Typography variant="h5" component="h1">
        Importar paquete
      </Typography>
      {result ? (
        <Alert severity="success">
          Paciente importada: {result.analyses} análisis y {result.symptoms} registros del diario.
          {result.already_imported && ' (ya estaba importada; se confirmó sin duplicar).'}
        </Alert>
      ) : (
        <Typography color="text.secondary">
          Escribe el código que te dio tu paciente o abre su enlace. Se usa una sola vez.
        </Typography>
      )}
      {error && <Alert severity="error">{error}</Alert>}
      <Card component="form" onSubmit={submit}>
        <CardContent>
          <Stack spacing={2}>
            <TextField
              label="Código"
              value={code}
              onChange={(e) => setCode(e.target.value)}
              autoComplete="off"
              slotProps={{ htmlInput: { spellCheck: false, style: { fontFamily: 'monospace' } } }}
              required
            />
            <Typography variant="body2" color="text.secondary">
              La copia queda bajo la custodia de tu institución, contigo como médica responsable. Si
              dejas de atenderla, la institución puede traspasarla a otra médica y la paciente lo verá.
            </Typography>
            <Button type="submit" variant="contained" disabled={!code.trim() || busy} sx={{ alignSelf: 'flex-start' }}>
              {busy ? 'Importando…' : 'Importar'}
            </Button>
          </Stack>
        </CardContent>
      </Card>
      <Button component={RouterLink} to="/medico" sx={{ alignSelf: 'flex-start' }}>
        Volver al inicio
      </Button>
    </Stack>
  );
}
