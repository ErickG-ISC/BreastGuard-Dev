import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Checkbox,
  CircularProgress,
  FormControl,
  FormControlLabel,
  FormGroup,
  FormLabel,
  Radio,
  RadioGroup,
  Stack,
  TextField,
  Typography,
} from '@mui/material';
import QRCode from 'qrcode';
import { useEffect, useRef, useState } from 'react';
import { Link as RouterLink } from 'react-router-dom';
import { api, errorMessage } from '../../api/client';
import SimpleMarkdown from '../../components/SimpleMarkdown';
import { formatDate, resultLabel } from './analysisLabels';

const MAX_ANALYSES = 10;
const EXPIRY = [
  { hours: 24, label: '24 horas' },
  { hours: 72, label: '3 días' },
  { hours: 168, label: '7 días' },
];

function Created({ result }) {
  const [qr, setQr] = useState('');
  const [copied, setCopied] = useState('');

  useEffect(() => {
    QRCode.toDataURL(result.link, { margin: 1, width: 240 })
      .then(setQr)
      .catch(() => setQr(''));
  }, [result.link]);

  async function copy(text, what) {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(what);
    } catch {
      setCopied('');
    }
  }

  return (
    <Stack spacing={2}>
      <Alert severity="warning">
        Este código solo se muestra ahora. Dáselo únicamente a tu médica: quien lo tenga puede importar la copia una
        vez. Vence el {formatDate(result.expires_at)}.
      </Alert>
      <Card>
        <CardContent>
          <Stack spacing={2} sx={{ alignItems: 'center', textAlign: 'center' }}>
            <Typography variant="overline">Código para tu médica</Typography>
            <Typography
              component="p"
              sx={{ fontFamily: 'monospace', fontSize: { xs: '1.05rem', sm: '1.4rem' }, wordBreak: 'break-all' }}
              aria-label="Código del paquete"
            >
              {result.code}
            </Typography>
            {qr && <Box component="img" src={qr} alt="Código QR con el enlace para importar" sx={{ width: 200, height: 200 }} />}
            <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1} sx={{ width: { xs: '100%', sm: 'auto' } }}>
              <Button variant="contained" onClick={() => copy(result.code, 'código')}>
                Copiar código
              </Button>
              <Button variant="outlined" onClick={() => copy(result.link, 'enlace')}>
                Copiar enlace
              </Button>
            </Stack>
            {copied && (
              <Typography variant="body2" color="text.secondary" role="status">
                Se copió el {copied}.
              </Typography>
            )}
          </Stack>
        </CardContent>
      </Card>
      <Button component={RouterLink} to="/compartidos">
        Ver mis paquetes
      </Button>
    </Stack>
  );
}

// CU-07: compartir una copia cifrada con la médica (M11)
export default function Share() {
  const [analyses, setAnalyses] = useState(null);
  const [consent, setConsent] = useState(null);
  const [form, setForm] = useState({
    analysis_ids: [],
    include_diary: true,
    include_questionnaire: true,
    include_notes: false,
    include_identity: false,
    expires_in_hours: 24,
    recipient_email: '',
  });
  const [accepted, setAccepted] = useState(false);
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);
  const [result, setResult] = useState(null);
  const savingRef = useRef(false);

  useEffect(() => {
    api
      .get('/analyses', { params: { limit: MAX_ANALYSES } })
      .then(({ data }) => setAnalyses(data.items))
      .catch(() => setAnalyses([]));
    api
      .get('/shares/consent')
      .then(({ data }) => setConsent(data))
      .catch(() => setError('No se pudo cargar el consentimiento.'));
  }, []);

  const toggle = (field) => (event) => {
    const value = event.target.checked;
    setForm((f) => ({ ...f, [field]: value, ...(field === 'include_diary' && !value ? { include_notes: false } : {}) }));
  };

  function toggleAnalysis(id) {
    setForm((f) => ({
      ...f,
      analysis_ids: f.analysis_ids.includes(id) ? f.analysis_ids.filter((x) => x !== id) : [...f.analysis_ids, id],
    }));
  }

  const nothing = !form.analysis_ids.length && !form.include_diary && !form.include_questionnaire;

  async function submit(event) {
    event.preventDefault();
    if (savingRef.current) return;
    savingRef.current = true;
    setSaving(true);
    setError('');
    try {
      const { data } = await api.post('/shares', {
        ...form,
        recipient_email: form.recipient_email.trim() || null,
        consent_accepted: accepted,
        consent_version: consent.version,
      });
      setResult(data);
    } catch (err) {
      setError(errorMessage(err, 'No se pudo crear el paquete.'));
    } finally {
      savingRef.current = false;
      setSaving(false);
    }
  }

  if (result) {
    return (
      <Stack spacing={2}>
        <Typography variant="h5" component="h1">
          Paquete listo
        </Typography>
        <Created result={result} />
      </Stack>
    );
  }

  return (
    <Stack spacing={2} component="form" onSubmit={submit}>
      <Typography variant="h5" component="h1">
        Compartir con mi médica
      </Typography>
      <Typography color="text.secondary">
        Crea un código de un solo uso para que tu médica importe una copia. Tus datos originales no cambian.
      </Typography>
      {error && <Alert severity="error">{error}</Alert>}

      <Card>
        <CardContent>
          <FormControl component="fieldset" sx={{ width: '100%' }}>
            <FormLabel component="legend">Análisis (hasta {MAX_ANALYSES})</FormLabel>
            {!analyses && <CircularProgress size={24} sx={{ mt: 1 }} />}
            {analyses && !analyses.length && (
              <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
                Aún no tienes análisis.
              </Typography>
            )}
            <FormGroup>
              {analyses?.map((a) => (
                <FormControlLabel
                  key={a.id}
                  control={<Checkbox checked={form.analysis_ids.includes(a.id)} onChange={() => toggleAnalysis(a.id)} />}
                  label={`${formatDate(a.created_at)} · ${resultLabel(a)}`}
                />
              ))}
            </FormGroup>
          </FormControl>
        </CardContent>
      </Card>

      <Card>
        <CardContent>
          <FormControl component="fieldset">
            <FormLabel component="legend">Qué más incluir</FormLabel>
            <FormGroup>
              <FormControlLabel
                control={<Checkbox checked={form.include_diary} onChange={toggle('include_diary')} />}
                label="Diario de síntomas y autoexploraciones (últimos 3 meses)"
              />
              <FormControlLabel
                control={
                  <Checkbox
                    checked={form.include_notes}
                    onChange={toggle('include_notes')}
                    disabled={!form.include_diary}
                  />
                }
                label="Mis notas escritas"
              />
              <FormControlLabel
                control={<Checkbox checked={form.include_questionnaire} onChange={toggle('include_questionnaire')} />}
                label="Cuestionario de antecedentes"
              />
              <FormControlLabel
                control={<Checkbox checked={form.include_identity} onChange={toggle('include_identity')} />}
                label="Mi nombre y mi edad"
              />
            </FormGroup>
          </FormControl>
        </CardContent>
      </Card>

      <Card>
        <CardContent>
          <Stack spacing={2}>
            <FormControl>
              <FormLabel id="vence">El código vence en</FormLabel>
              <RadioGroup
                row
                aria-labelledby="vence"
                value={form.expires_in_hours}
                onChange={(e) => setForm((f) => ({ ...f, expires_in_hours: Number(e.target.value) }))}
              >
                {EXPIRY.map((o) => (
                  <FormControlLabel key={o.hours} value={o.hours} control={<Radio />} label={o.label} />
                ))}
              </RadioGroup>
            </FormControl>
            <TextField
              label="Correo de tu médica (opcional)"
              type="email"
              value={form.recipient_email}
              onChange={(e) => setForm((f) => ({ ...f, recipient_email: e.target.value }))}
              helperText="Si tiene cuenta, recibirá un aviso discreto. Aun así necesitará el código."
            />
          </Stack>
        </CardContent>
      </Card>

      <Card>
        <CardContent>
          <Stack spacing={1}>
            {!consent ? (
              <CircularProgress size={24} />
            ) : (
              <Box
                sx={{ maxHeight: 320, overflowY: 'auto', border: 1, borderColor: 'divider', borderRadius: 1, p: 2 }}
                tabIndex={0}
                aria-label="Consentimiento para compartir"
              >
                <SimpleMarkdown source={consent.text} />
              </Box>
            )}
            <FormControlLabel
              control={<Checkbox checked={accepted} onChange={(e) => setAccepted(e.target.checked)} />}
              label="Leí y acepto compartir esta copia con mi médica y su institución."
            />
          </Stack>
        </CardContent>
      </Card>

      <Button type="submit" variant="contained" size="large" disabled={!accepted || !consent || nothing || saving}>
        {saving ? 'Preparando…' : 'Crear código'}
      </Button>
    </Stack>
  );
}
