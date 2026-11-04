import {
  Alert,
  Button,
  Card,
  CardActions,
  CardContent,
  Chip,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogContentText,
  DialogTitle,
  Stack,
  Typography,
} from '@mui/material';
import { useCallback, useEffect, useState } from 'react';
import { Link as RouterLink } from 'react-router-dom';
import { api, errorMessage } from '../../api/client';
import { formatDate } from './analysisLabels';

const STATUS = {
  activo: { label: 'Activo', color: 'primary' },
  importando: { label: 'Importándose', color: 'warning' },
  importado: { label: 'Importado', color: 'success' },
  revocado: { label: 'Revocado', color: 'default' },
  caducado: { label: 'Vencido', color: 'default' },
};
const SECTIONS = {
  analyses: 'análisis',
  diary: 'diario',
  questionnaire: 'cuestionario',
  notes: 'notas',
  identity: 'nombre y edad',
};

function eventText(e) {
  if (e.kind === 'creado') return 'Creado';
  if (e.kind === 'revocado') return 'Revocado';
  if (e.kind === 'caducado') return 'Venció sin usarse';
  if (e.kind === 'importado') return `Importado por ${e.doctor_name ?? 'una médica'} (${e.institution_name ?? 'su institución'})`;
  if (e.kind === 'reasignado') return `Tu caso pasó a ${e.doctor_name ?? 'otra médica'} (${e.institution_name ?? 'la misma institución'})`;
  return 'Intento fallido';
}

// CU-07: mis paquetes compartidos, su historia y revocar los activos
export default function MyShares() {
  const [items, setItems] = useState(null);
  const [error, setError] = useState('');
  const [toRevoke, setToRevoke] = useState(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    api
      .get('/shares')
      .then(({ data }) => {
        setItems(data.items);
        setError('');
      })
      .catch((err) => setError(errorMessage(err, 'No se pudieron cargar tus paquetes.')));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function revoke() {
    setBusy(true);
    try {
      await api.delete(`/shares/${toRevoke.id}`);
      setToRevoke(null);
      load();
    } catch (err) {
      setError(errorMessage(err, 'No se pudo revocar.'));
      setToRevoke(null);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Stack spacing={2}>
      <Stack direction="row" sx={{ justifyContent: 'space-between', alignItems: 'center', gap: 1, flexWrap: 'wrap' }}>
        <Typography variant="h5" component="h1">
          Mis paquetes
        </Typography>
        <Button variant="contained" component={RouterLink} to="/compartir">
          Compartir
        </Button>
      </Stack>
      {error && <Alert severity="error">{error}</Alert>}
      {!items && !error && <CircularProgress sx={{ alignSelf: 'center' }} />}
      {items && !items.length && <Typography color="text.secondary">Aún no has compartido nada.</Typography>}
      {items?.map((p) => (
        <Card key={p.id}>
          <CardContent>
            <Stack direction="row" sx={{ justifyContent: 'space-between', alignItems: 'flex-start', gap: 1 }}>
              <Typography variant="subtitle1" component="h2">
                {formatDate(p.created_at)}
              </Typography>
              <Chip size="small" color={STATUS[p.status].color} label={STATUS[p.status].label} />
            </Stack>
            <Typography variant="body2" color="text.secondary">
              Incluye:{' '}
              {Object.entries(p.sections)
                .filter(([, on]) => on)
                .map(([key]) => (key === 'analyses' ? `${p.analyses_count} ${SECTIONS.analyses}` : SECTIONS[key]))
                .join(', ')}
            </Typography>
            {p.status === 'activo' && (
              <Typography variant="body2" color="text.secondary">
                Vence el {formatDate(p.expires_at)}
              </Typography>
            )}
            <Stack component="ul" sx={{ pl: 2, my: 1 }}>
              {p.events.map((e) => (
                <Typography component="li" variant="body2" key={`${e.kind}-${e.occurred_at}`}>
                  {formatDate(e.occurred_at)}: {eventText(e)}
                </Typography>
              ))}
            </Stack>
          </CardContent>
          {p.status === 'activo' && (
            <CardActions>
              <Button color="error" onClick={() => setToRevoke(p)} disabled={busy}>
                Revocar
              </Button>
            </CardActions>
          )}
        </Card>
      ))}
      <Dialog open={Boolean(toRevoke)} onClose={() => setToRevoke(null)}>
        <DialogTitle>¿Revocar este paquete?</DialogTitle>
        <DialogContent>
          <DialogContentText>El código dejará de servir y se borrará la copia cifrada. No se puede deshacer.</DialogContentText>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setToRevoke(null)}>Cancelar</Button>
          <Button color="error" variant="contained" onClick={revoke} disabled={busy}>
            Revocar
          </Button>
        </DialogActions>
      </Dialog>
    </Stack>
  );
}
