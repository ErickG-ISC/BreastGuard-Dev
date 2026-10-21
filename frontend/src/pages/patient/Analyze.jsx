import { Alert, Box, Button, LinearProgress, Paper, Stack, Typography } from '@mui/material';
import { useEffect, useRef, useState } from 'react';
import { Link as RouterLink, useNavigate } from 'react-router-dom';
import { api, errorMessage } from '../../api/client';
import Layout from '../../components/Layout';
import { ImageGuide } from './PatientHome';

const MAX_MB = 10;
const ACCEPTED = ['image/jpeg', 'image/png'];

export default function Analyze() {
  const navigate = useNavigate();
  const cameraInput = useRef(null);
  const galleryInput = useRef(null);
  const [file, setFile] = useState(null);
  const [preview, setPreview] = useState('');
  const [phase, setPhase] = useState('idle'); // idle | uploading | analyzing
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState('');

  useEffect(() => () => preview && URL.revokeObjectURL(preview), [preview]);

  function choose(event) {
    const selected = event.target.files?.[0];
    event.target.value = '';
    if (!selected) return;
    if (!ACCEPTED.includes(selected.type)) {
      setError('Formato no compatible. Usa una imagen JPG o PNG.');
      return;
    }
    if (selected.size > MAX_MB * 1024 * 1024) {
      setError(`La imagen supera ${MAX_MB} MB.`);
      return;
    }
    setError('');
    setFile(selected);
    setPreview(URL.createObjectURL(selected));
  }

  async function analyze() {
    setError('');
    setPhase('uploading');
    setProgress(0);
    const form = new FormData();
    form.append('file', file);
    try {
      const { data } = await api.post('/analyses', form, {
        onUploadProgress: (e) => {
          if (e.total) {
            const pct = Math.round((e.loaded / e.total) * 100);
            setProgress(pct);
            if (pct >= 100) setPhase('analyzing');
          }
        },
      });
      navigate(`/resultado/${data.id}`, { state: { analysis: data } });
    } catch (err) {
      setPhase('idle');
      setError(errorMessage(err, 'No se pudo analizar la imagen.'));
    }
  }

  const busy = phase !== 'idle';

  return (
    <Layout>
      <Stack spacing={2}>
        <Typography variant="h5" component="h1">
          Analizar una ecografía
        </Typography>
        <Paper sx={{ p: { xs: 2, sm: 3 } }}>
          <Stack spacing={2}>
            <input ref={cameraInput} type="file" accept="image/*" capture="environment" hidden onChange={choose} />
            <input ref={galleryInput} type="file" accept="image/jpeg,image/png" hidden onChange={choose} />
            <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1}>
              <Button variant="outlined" onClick={() => galleryInput.current.click()} disabled={busy}>
                Elegir de la galería
              </Button>
              <Button variant="outlined" onClick={() => cameraInput.current.click()} disabled={busy}>
                Tomar foto
              </Button>
            </Stack>
            {error && <Alert severity="error">{error}</Alert>}
            {preview && (
              <Box
                component="img"
                src={preview}
                alt="Vista previa de la ecografía seleccionada"
                sx={{ width: '100%', maxHeight: 360, objectFit: 'contain', bgcolor: 'black', borderRadius: 1 }}
              />
            )}
            {busy && (
              <Box>
                <Typography variant="body2" sx={{ mb: 1 }}>
                  {phase === 'uploading' ? `Subiendo imagen… ${progress}%` : 'Analizando la imagen, esto puede tardar unos segundos…'}
                </Typography>
                <LinearProgress
                  variant={phase === 'uploading' ? 'determinate' : 'indeterminate'}
                  value={progress}
                />
              </Box>
            )}
            <Stack direction="row" spacing={1} sx={{ justifyContent: 'space-between' }}>
              <Button component={RouterLink} to="/paciente" disabled={busy}>
                Volver
              </Button>
              <Button variant="contained" onClick={analyze} disabled={!file || busy}>
                Analizar
              </Button>
            </Stack>
          </Stack>
        </Paper>
        <ImageGuide />
      </Stack>
    </Layout>
  );
}
