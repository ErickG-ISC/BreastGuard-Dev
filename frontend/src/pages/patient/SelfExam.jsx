import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  CircularProgress,
  FormControlLabel,
  LinearProgress,
  Radio,
  RadioGroup,
  Stack,
  TextField,
  Typography,
} from '@mui/material';
import { useEffect, useState } from 'react';
import { Link as RouterLink, useNavigate } from 'react-router-dom';
import { api, errorMessage } from '../../api/client';
import SelfExamIllustration from '../../components/SelfExamIllustration';
import { formatDate } from './analysisLabels';

const CHANGE_OPTIONS = [
  { value: 'si', label: 'Sí, noté algo distinto' },
  { value: 'no', label: 'No noté cambios' },
  { value: 'no_segura', label: 'No estoy segura' },
];

function Intro({ guide, last, onStart, starting }) {
  return (
    <Card>
      <CardContent>
        <Stack spacing={2}>
          <Chip label="Borrador · contenido educativo general" size="small" sx={{ alignSelf: 'start' }} />
          <Typography variant="body1">{guide.intro}</Typography>
          {last && (
            <Typography variant="body2" color="text.secondary">
              Tu última autoexploración fue el {formatDate(last.finished_at)}.
            </Typography>
          )}
          <Button variant="contained" onClick={onStart} disabled={starting}>
            Comenzar ({guide.steps.length} pasos)
          </Button>
        </Stack>
      </CardContent>
    </Card>
  );
}

function Step({ step, index, total, onBack, onNext }) {
  return (
    <Card>
      <CardContent>
        <Stack spacing={2}>
          <Box>
            <Typography variant="overline" color="text.secondary">
              Paso {index + 1} de {total}
            </Typography>
            <LinearProgress
              variant="determinate"
              value={((index + 1) / total) * 100}
              aria-label={`Progreso: paso ${index + 1} de ${total}`}
              sx={{ mt: 0.5, borderRadius: 1 }}
            />
          </Box>
          <SelfExamIllustration name={step.illustration} label={step.title} />
          <Typography variant="h6" component="h2">
            {step.title}
          </Typography>
          <Box component="ol" sx={{ pl: 2.5, m: 0 }}>
            {step.instructions.map((line) => (
              <Typography component="li" variant="body2" key={line} sx={{ mb: 0.5 }}>
                {line}
              </Typography>
            ))}
          </Box>
          <Box sx={{ bgcolor: 'action.hover', borderRadius: 2, p: 2 }}>
            <Typography variant="subtitle2" component="h3" sx={{ mb: 0.5 }}>
              Qué observar
            </Typography>
            <Box component="ul" sx={{ pl: 2.5, m: 0 }}>
              {step.look_for.map((line) => (
                <Typography component="li" variant="body2" key={line}>
                  {line}
                </Typography>
              ))}
            </Box>
          </Box>
          <Stack direction="row" spacing={1} sx={{ justifyContent: 'space-between' }}>
            <Button variant="outlined" onClick={onBack} disabled={index === 0}>
              Anterior
            </Button>
            <Button variant="contained" onClick={onNext}>
              {index + 1 === total ? 'Terminar' : 'Siguiente'}
            </Button>
          </Stack>
        </Stack>
      </CardContent>
    </Card>
  );
}

function FinishForm({ onSubmit, saving }) {
  const [answer, setAnswer] = useState('');
  const [note, setNote] = useState('');

  function handleSubmit(event) {
    event.preventDefault();
    onSubmit(answer, note);
  }

  return (
    <Card>
      <CardContent>
        <Stack spacing={2} component="form" onSubmit={handleSubmit}>
          <Typography variant="h6" component="h2" id="cambio-label">
            ¿Notaste algo distinto a la vez pasada?
          </Typography>
          <RadioGroup aria-labelledby="cambio-label" value={answer} onChange={(e) => setAnswer(e.target.value)}>
            {CHANGE_OPTIONS.map((option) => (
              <FormControlLabel key={option.value} value={option.value} control={<Radio />} label={option.label} />
            ))}
          </RadioGroup>
          <TextField
            label="Nota (opcional)"
            multiline
            minRows={2}
            value={note}
            onChange={(e) => setNote(e.target.value)}
            slotProps={{ htmlInput: { maxLength: 1000 } }}
            helperText="Solo tú puedes verla."
          />
          <Button type="submit" variant="contained" disabled={!answer || saving}>
            Guardar
          </Button>
        </Stack>
      </CardContent>
    </Card>
  );
}

function Done({ exam, closing }) {
  const navigate = useNavigate();
  const changed = exam.noticed_change === 'si';
  // Fecha local en formato AAAA-MM-DD para prellenar el diario
  const today = new Date().toLocaleDateString('en-CA');

  return (
    <Card>
      <CardContent>
        <Stack spacing={2}>
          <Typography variant="h6" component="h2">
            Autoexploración registrada
          </Typography>
          {changed ? (
            <Alert severity="info">
              Gracias por registrarlo. {closing}
            </Alert>
          ) : (
            <Typography variant="body2">
              Conocer tu cuerpo te ayuda a notar cambios. Si en algún momento notas algo distinto, consulta a tu
              médico, aunque sea entre revisiones.
            </Typography>
          )}
          <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1}>
            {changed && (
              <Button
                variant="contained"
                onClick={() => navigate('/diario', { state: { selfExamId: exam.id, entryDate: today } })}
              >
                Registrar en el diario
              </Button>
            )}
            <Button component={RouterLink} to="/paciente" variant={changed ? 'text' : 'contained'}>
              Volver al inicio
            </Button>
          </Stack>
        </Stack>
      </CardContent>
    </Card>
  );
}

export default function SelfExam() {
  const [guide, setGuide] = useState(null);
  const [last, setLast] = useState(null);
  const [exam, setExam] = useState(null);
  const [step, setStep] = useState(-1); // -1: introducción; steps.length: pregunta final
  const [done, setDone] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    api
      .get('/self-exam/guide')
      .then(({ data }) => setGuide(data))
      .catch((err) => setError(errorMessage(err, 'No se pudo cargar la guía.')));
    api
      .get('/self-exams/latest')
      .then(({ data }) => setLast(data))
      .catch(() => setLast(null));
  }, []);

  async function begin() {
    setBusy(true);
    setError('');
    try {
      const { data } = await api.post('/self-exams');
      setExam(data);
      setStep(0);
    } catch (err) {
      setError(errorMessage(err, 'No se pudo iniciar la autoexploración.'));
    } finally {
      setBusy(false);
    }
  }

  async function submit(answer, note) {
    setBusy(true);
    setError('');
    try {
      const { data } = await api.post(`/self-exams/${exam.id}/finish`, {
        noticed_change: answer,
        note: note || null,
      });
      setDone(data);
    } catch (err) {
      setError(errorMessage(err, 'No se pudo guardar.'));
    } finally {
      setBusy(false);
    }
  }

  const total = guide?.steps.length ?? 0;

  // Cada paso empieza arriba, sobre todo en móvil donde la tarjeta es larga
  useEffect(() => {
    window.scrollTo({ top: 0 });
  }, [step, done]);

  return (
    <Stack spacing={2}>
      <Typography variant="h5" component="h1">
        Autoexploración
      </Typography>
      {error && <Alert severity="error">{error}</Alert>}
      {!guide && !error && <CircularProgress sx={{ alignSelf: 'center' }} />}
      {guide && done && <Done exam={done} closing={guide.closing} />}
      {guide && !done && step === -1 && <Intro guide={guide} last={last} onStart={begin} starting={busy} />}
      {guide && !done && step >= 0 && step < total && (
        <Step
          step={guide.steps[step]}
          index={step}
          total={total}
          onBack={() => setStep((s) => s - 1)}
          onNext={() => setStep((s) => s + 1)}
        />
      )}
      {guide && !done && step === total && <FinishForm onSubmit={submit} saving={busy} />}
      {guide && (
        <Typography variant="caption" color="text.secondary">
          {guide.status_note}
        </Typography>
      )}
    </Stack>
  );
}
