import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Paper,
  Slider,
  Stack,
  Typography,
} from '@mui/material';
import { useCallback, useEffect, useState } from 'react';
import { Link as RouterLink, useLocation, useParams } from 'react-router-dom';
import { api, errorMessage } from '../../api/client';
import { CLASS_LABELS, LEVEL_SEVERITY, formatDate, resultLabel } from './analysisLabels';

function HeatmapViewer({ imageUrl, heatmapUrl, onExpired }) {
  const [opacity, setOpacity] = useState(60);
  const [retried, setRetried] = useState(false);
  // Si una URL firmada expiró se piden URLs nuevas UNA vez; si vuelve a fallar no se insiste
  const handleError = () => {
    if (!retried) {
      setRetried(true);
      onExpired();
    }
  };
  return (
    <Stack spacing={1}>
      <Box sx={{ position: 'relative', width: '100%', bgcolor: 'imaging.main', borderRadius: 1, overflow: 'hidden' }}>
        <Box component="img" src={imageUrl} alt="Ecografía analizada" onError={handleError} sx={{ display: 'block', width: '100%' }} />
        <Box
          component="img"
          src={heatmapUrl}
          alt="Mapa de calor superpuesto"
          onError={handleError}
          sx={{ position: 'absolute', inset: 0, width: '100%', height: '100%', opacity: opacity / 100 }}
        />
      </Box>
      <Typography id="opacidad" variant="body2">
        Intensidad del mapa de calor
      </Typography>
      <Slider aria-labelledby="opacidad" value={opacity} onChange={(_, v) => setOpacity(v)} min={0} max={100} />
      <Typography variant="caption" color="text.secondary">
        Las zonas en rojo y amarillo son las que más influyeron en la estimación del modelo. No indican por sí solas un
        problema.
      </Typography>
    </Stack>
  );
}

export default function Result() {
  const { id } = useParams();
  const location = useLocation();
  const [analysis, setAnalysis] = useState(location.state?.analysis ?? null);
  const [error, setError] = useState('');

  const load = useCallback(() => {
    api
      .get(`/analyses/${id}`)
      .then(({ data }) => setAnalysis(data))
      .catch((err) => setError(errorMessage(err, 'No se pudo cargar el resultado.')));
  }, [id]);

  useEffect(() => {
    // Sin datos previos, o creado sin URLs (falló la firma): se piden de nuevo
    if (!location.state?.analysis?.image_url) load();
  }, [load, location.state]);

  if (error) {
    return (
      <>
        <Alert severity="error">{error}</Alert>
        <Button component={RouterLink} to="/historial" sx={{ mt: 2 }}>
          Ir al historial
        </Button>
      </>
    );
  }
  if (!analysis) {
    return (
      <>
        <Box sx={{ display: 'flex', justifyContent: 'center', py: 6 }}>
          <CircularProgress />
        </Box>
      </>
    );
  }

  const { report } = analysis;
  return (
    <>
      <Stack spacing={2}>
        {report.demo_notice && <Alert severity="warning">{report.demo_notice}</Alert>}
        <Paper sx={{ p: { xs: 2, sm: 3 } }}>
          <Stack spacing={2}>
            <Typography variant="overline" color="text.secondary">
              {formatDate(analysis.created_at)}
            </Typography>
            <Typography variant="h5" component="h1">
              {report.title}
            </Typography>
            <Stack direction="row" sx={{ gap: 1, flexWrap: 'wrap' }}>
              <Chip label={resultLabel(analysis)} />
              <Chip variant="outlined" label={`Confianza ${report.confidence_words}`} />
            </Stack>
            {report.paragraphs.map((p) => (
              <Typography key={p} variant="body1">
                {p}
              </Typography>
            ))}
            <Alert severity={LEVEL_SEVERITY[report.level] ?? 'info'}>{report.recommendation}</Alert>
          </Stack>
        </Paper>

        {analysis.image_url && (
          <Paper sx={{ p: { xs: 2, sm: 3 } }}>
            <HeatmapViewer imageUrl={analysis.image_url} heatmapUrl={analysis.heatmap_url} onExpired={load} />
          </Paper>
        )}

        <Accordion disableGutters>
          <AccordionSummary>
            <Typography variant="body2">Ver detalle técnico</Typography>
          </AccordionSummary>
          <AccordionDetails>
            <Typography variant="body2" sx={{ mb: 1 }}>
              Modelo: {analysis.model_version}
            </Typography>
            {report.level === 'inconclusive' && (
              <Typography variant="body2" color="warning.main" sx={{ mb: 1 }}>
                Resultado no concluyente: estas cifras no deben interpretarse como una estimación.
              </Typography>
            )}
            {Object.entries(analysis.probabilities).map(([name, value]) => (
              <Typography variant="body2" key={name}>
                {CLASS_LABELS[name] ?? name}: {Math.round(value * 100)} de cada 100
              </Typography>
            ))}
          </AccordionDetails>
        </Accordion>

        <Alert severity="info" variant="outlined">
          {report.disclaimer}
        </Alert>
        <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1}>
          <Button component={RouterLink} to="/analizar" variant="contained">
            Analizar otra imagen
          </Button>
          <Button component={RouterLink} to="/historial">
            Ver historial
          </Button>
        </Stack>
      </Stack>
    </>
  );
}
