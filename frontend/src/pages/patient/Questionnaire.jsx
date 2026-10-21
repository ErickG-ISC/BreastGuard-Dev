import {
  Alert,
  Box,
  Button,
  Checkbox,
  Chip,
  CircularProgress,
  FormControl,
  FormControlLabel,
  FormGroup,
  FormLabel,
  Paper,
  Radio,
  RadioGroup,
  Stack,
  TextField,
  Typography,
} from '@mui/material';
import { useEffect, useState } from 'react';
import { Link as RouterLink } from 'react-router-dom';
import { api, errorMessage } from '../../api/client';
import Layout from '../../components/Layout';

function initialAnswers(questions) {
  const answers = {};
  questions.forEach((q) => {
    if (q.type === 'multi') answers[q.id] = [];
    else if (q.type === 'boolean') answers[q.id] = null;
    else answers[q.id] = '';
  });
  return answers;
}

function Question({ question, value, onChange }) {
  if (question.type === 'number') {
    return (
      <TextField
        label={question.label}
        type="number"
        slotProps={{ htmlInput: { min: question.min, max: question.max, inputMode: 'numeric' } }}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        required
      />
    );
  }
  if (question.type === 'multi') {
    return (
      <FormControl component="fieldset">
        <FormLabel component="legend">{question.label}</FormLabel>
        <FormGroup>
          {question.options.map((option) => (
            <FormControlLabel
              key={option.value}
              control={
                <Checkbox
                  checked={value.includes(option.value)}
                  onChange={(e) =>
                    onChange(e.target.checked ? [...value, option.value] : value.filter((v) => v !== option.value))
                  }
                />
              }
              label={option.label}
            />
          ))}
        </FormGroup>
      </FormControl>
    );
  }
  const options =
    question.type === 'boolean'
      ? [
          { value: 'true', label: 'Sí' },
          { value: 'false', label: 'No' },
        ]
      : question.options;
  const current = question.type === 'boolean' ? (value === null ? '' : String(value)) : value;
  return (
    <FormControl component="fieldset" required>
      <FormLabel component="legend">{question.label}</FormLabel>
      <RadioGroup
        value={current}
        onChange={(e) => onChange(question.type === 'boolean' ? e.target.value === 'true' : e.target.value)}
      >
        {options.map((option) => (
          <FormControlLabel key={option.value} value={option.value} control={<Radio />} label={option.label} />
        ))}
      </RadioGroup>
    </FormControl>
  );
}

export function QuestionnaireResult({ result }) {
  const severity = { sin_factores: 'success', factores_a_comentar: 'info', sintomas_a_consultar: 'warning' }[result.level];
  return (
    <Stack spacing={2}>
      <Alert severity={severity ?? 'info'}>{result.message}</Alert>
      {result.factors.length > 0 && (
        <Box>
          <Typography variant="subtitle1" component="h2">
            Factores a comentar con tu médico
          </Typography>
          <Stack direction="row" sx={{ flexWrap: 'wrap', gap: 1, mt: 1 }}>
            {result.factors.map((factor) => (
              <Chip key={factor.code} label={factor.label} color={factor.kind === 'symptom' ? 'warning' : 'default'} />
            ))}
          </Stack>
        </Box>
      )}
      <Typography variant="body2" color="text.secondary">
        Esto no es una probabilidad ni un diagnóstico: solo resume respuestas que vale la pena conversar en consulta.
      </Typography>
    </Stack>
  );
}

export default function Questionnaire() {
  const [definition, setDefinition] = useState(null);
  const [answers, setAnswers] = useState({});
  const [result, setResult] = useState(null);
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    api
      .get('/questionnaire/current')
      .then(({ data }) => {
        setDefinition(data);
        setAnswers(initialAnswers(data.questions));
      })
      .catch((err) => setError(errorMessage(err, 'No se pudo cargar el cuestionario.')));
  }, []);

  async function handleSubmit(event) {
    event.preventDefault();
    const missing = definition.questions.find((q) => q.type !== 'multi' && (answers[q.id] === '' || answers[q.id] === null));
    if (missing) return setError(`Falta responder: ${missing.label}`);
    setError('');
    setSaving(true);
    try {
      const { data } = await api.post('/questionnaires', {
        version: definition.version,
        answers: { ...answers, age: Number(answers.age) },
      });
      setResult(data);
      window.scrollTo({ top: 0, behavior: 'smooth' });
    } catch (err) {
      setError(errorMessage(err, 'No se pudo guardar el cuestionario.'));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Layout>
      <Paper sx={{ p: { xs: 2, sm: 3 } }}>
        <Typography variant="h5" component="h1" sx={{ mb: 1 }}>
          Cuestionario de antecedentes
        </Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          Tus respuestas nos ayudan a recordarte qué conviene comentar con tu médica o médico. Puedes actualizarlo cuando quieras.
        </Typography>
        {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
        {result ? (
          <Stack spacing={2}>
            <QuestionnaireResult result={result} />
            <Button component={RouterLink} to="/paciente" variant="contained">
              Continuar
            </Button>
          </Stack>
        ) : !definition ? (
          <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
            <CircularProgress />
          </Box>
        ) : (
          <Stack component="form" spacing={3} onSubmit={handleSubmit}>
            {definition.questions.map((question) => (
              <Question
                key={question.id}
                question={question}
                value={answers[question.id]}
                onChange={(value) => setAnswers({ ...answers, [question.id]: value })}
              />
            ))}
            <Stack direction="row" spacing={1} sx={{ justifyContent: 'space-between' }}>
              <Button component={RouterLink} to="/paciente">
                Responder después
              </Button>
              <Button type="submit" variant="contained" disabled={saving}>
                {saving ? 'Guardando…' : 'Guardar respuestas'}
              </Button>
            </Stack>
          </Stack>
        )}
      </Paper>
    </Layout>
  );
}
