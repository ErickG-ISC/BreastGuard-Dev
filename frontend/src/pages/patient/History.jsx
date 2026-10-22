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
  DialogContentText,
  DialogTitle,
  Stack,
  Typography,
} from '@mui/material';
import { useCallback, useEffect, useState } from 'react';
import { Link as RouterLink } from 'react-router-dom';
import { api, errorMessage } from '../../api/client';
import { LEVEL_SEVERITY, formatDate, resultLabel } from './analysisLabels';

const PAGE = 10;

export default function History() {
  const [page, setPage] = useState({ items: [], total: 0, offset: 0 });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [toDelete, setToDelete] = useState(null);
  const [deleting, setDeleting] = useState(false);

  const load = useCallback(async (offset = 0) => {
    setLoading(true);
    try {
      const { data } = await api.get('/analyses', { params: { limit: PAGE, offset } });
      setPage(data);
      setError('');
    } catch (err) {
      setError(errorMessage(err, 'No se pudo cargar el historial.'));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load(0);
  }, [load]);

  async function confirmDelete() {
    setDeleting(true);
    try {
      await api.delete(`/analyses/${toDelete.id}`);
      setToDelete(null);
      await load(page.items.length === 1 && page.offset > 0 ? page.offset - PAGE : page.offset);
    } catch (err) {
      setError(errorMessage(err, 'No se pudo eliminar el análisis.'));
      setToDelete(null);
    } finally {
      setDeleting(false);
    }
  }

  return (
    <>
      <Stack spacing={2}>
        <Stack direction="row" sx={{ alignItems: 'center', justifyContent: 'space-between', gap: 1, flexWrap: 'wrap' }}>
          <Typography variant="h5" component="h1">
            Tu historial
          </Typography>
          <Button component={RouterLink} to="/analizar" variant="contained">
            Nuevo análisis
          </Button>
        </Stack>
        {error && <Alert severity="error">{error}</Alert>}
        {page.items.find((item) => item.report.demo_notice) && (
          <Alert severity="warning">{page.items.find((item) => item.report.demo_notice).report.demo_notice}</Alert>
        )}
        {loading ? (
          <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
            <CircularProgress />
          </Box>
        ) : page.items.length === 0 ? (
          <Typography>Aún no tienes análisis.</Typography>
        ) : (
          page.items.map((item) => (
            <Card key={item.id} variant="outlined">
              <CardContent>
                <Typography variant="overline" color="text.secondary">
                  {formatDate(item.created_at)}
                </Typography>
                <Typography variant="h6" component="h2">
                  {item.report.title}
                </Typography>
                <Stack direction="row" sx={{ gap: 1, flexWrap: 'wrap', mt: 1 }}>
                  <Chip size="small" color={LEVEL_SEVERITY[item.report.level] ?? 'default'} label={resultLabel(item)} />
                  <Chip size="small" variant="outlined" label={`Confianza ${item.report.confidence_words}`} />
                </Stack>
              </CardContent>
              <CardActions sx={{ px: 2, pb: 2, gap: 1, flexWrap: 'wrap' }}>
                <Button component={RouterLink} to={`/resultado/${item.id}`} size="small" variant="outlined">
                  Ver resultado
                </Button>
                <Button size="small" color="error" onClick={() => setToDelete(item)}>
                  Eliminar
                </Button>
              </CardActions>
            </Card>
          ))
        )}
        {page.total > PAGE && (
          <Stack direction="row" spacing={1} sx={{ justifyContent: 'center' }}>
            <Button disabled={page.offset === 0} onClick={() => load(page.offset - PAGE)}>
              Anteriores
            </Button>
            <Button disabled={page.offset + PAGE >= page.total} onClick={() => load(page.offset + PAGE)}>
              Siguientes
            </Button>
          </Stack>
        )}
      </Stack>
      <Dialog open={Boolean(toDelete)} onClose={() => setToDelete(null)}>
        <DialogTitle>¿Eliminar este análisis?</DialogTitle>
        <DialogContent>
          <DialogContentText>
            Se borrarán para siempre el resultado, la imagen y el mapa de calor. Esta acción no se puede deshacer.
          </DialogContentText>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setToDelete(null)}>Cancelar</Button>
          <Button color="error" variant="contained" onClick={confirmDelete} disabled={deleting}>
            {deleting ? 'Eliminando…' : 'Eliminar'}
          </Button>
        </DialogActions>
      </Dialog>
    </>
  );
}
