import {
  Alert,
  Box,
  Button,
  Card,
  CardActionArea,
  CardContent,
  Checkbox,
  CircularProgress,
  FormControlLabel,
  Link,
  Paper,
  Stack,
  Step,
  StepLabel,
  Stepper,
  TextField,
  Typography,
} from '@mui/material';
import { useEffect, useState } from 'react';
import { Link as RouterLink, useNavigate } from 'react-router-dom';
import { api, errorMessage } from '../api/client';
import { useAuth } from '../auth/AuthContext';
import Layout from '../components/Layout';
import SimpleMarkdown from '../components/SimpleMarkdown';

const STEPS = ['Tus datos', 'Consentimiento', 'Plan'];

export default function Register() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [step, setStep] = useState(0);
  const [form, setForm] = useState({ full_name: '', email: '', password: '', confirm: '' });
  const [consent, setConsent] = useState(null);
  const [accepted, setAccepted] = useState(false);
  const [plans, setPlans] = useState([]);
  const [planCode, setPlanCode] = useState('basico');
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    api.get('/consent/current').then(({ data }) => setConsent(data)).catch(() => setError('No se pudo cargar el consentimiento.'));
    api.get('/plans').then(({ data }) => setPlans(data)).catch(() => setError('No se pudieron cargar los planes.'));
  }, []);

  const update = (field) => (event) => setForm({ ...form, [field]: event.target.value });

  function nextFromData(event) {
    event.preventDefault();
    if (form.password.length < 8) return setError('La contraseña debe tener al menos 8 caracteres.');
    if (form.password !== form.confirm) return setError('Las contraseñas no coinciden.');
    setError('');
    setStep(1);
  }

  async function submit() {
    setError('');
    setSubmitting(true);
    try {
      await api.post('/auth/register', {
        full_name: form.full_name,
        email: form.email,
        password: form.password,
        consent_accepted: accepted,
        consent_version: consent.version,
        plan_code: planCode,
      });
      await login(form.email, form.password);
      navigate('/cuestionario', { replace: true });
    } catch (err) {
      setError(errorMessage(err, 'No se pudo crear la cuenta.'));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Layout>
      <Paper sx={{ p: { xs: 2, sm: 3 } }}>
        <Typography variant="h5" component="h1" sx={{ mb: 2 }}>
          Crear cuenta
        </Typography>
        <Stepper activeStep={step} alternativeLabel sx={{ mb: 3 }}>
          {STEPS.map((label) => (
            <Step key={label}>
              <StepLabel>{label}</StepLabel>
            </Step>
          ))}
        </Stepper>
        {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}

        {step === 0 && (
          <Stack component="form" spacing={2} onSubmit={nextFromData}>
            <TextField label="Nombre completo" value={form.full_name} onChange={update('full_name')} required />
            <TextField label="Email" type="email" autoComplete="email" value={form.email} onChange={update('email')} required />
            <TextField
              label="Contraseña"
              type="password"
              autoComplete="new-password"
              helperText="Al menos 8 caracteres."
              value={form.password}
              onChange={update('password')}
              required
            />
            <TextField
              label="Repite la contraseña"
              type="password"
              autoComplete="new-password"
              value={form.confirm}
              onChange={update('confirm')}
              required
            />
            <Button type="submit" variant="contained" size="large">
              Continuar
            </Button>
            <Typography variant="body2">
              ¿Ya tienes cuenta?{' '}
              <Link component={RouterLink} to="/login">
                Inicia sesión
              </Link>
            </Typography>
          </Stack>
        )}

        {step === 1 && (
          <Stack spacing={2}>
            {!consent ? (
              <Box sx={{ display: 'flex', justifyContent: 'center', py: 3 }}>
                <CircularProgress />
              </Box>
            ) : (
              <Box
                sx={{ maxHeight: 360, overflowY: 'auto', border: 1, borderColor: 'divider', borderRadius: 1, p: 2 }}
                tabIndex={0}
                aria-label="Texto del consentimiento informado"
              >
                <SimpleMarkdown source={consent.text} />
              </Box>
            )}
            <FormControlLabel
              control={<Checkbox checked={accepted} onChange={(e) => setAccepted(e.target.checked)} />}
              label="Leí y acepto el consentimiento informado. Entiendo que BreastGuard es una herramienta de apoyo y no un diagnóstico."
            />
            <Stack direction="row" spacing={1} sx={{ justifyContent: 'space-between' }}>
              <Button onClick={() => setStep(0)}>Atrás</Button>
              <Button variant="contained" disabled={!accepted || !consent} onClick={() => setStep(2)}>
                Continuar
              </Button>
            </Stack>
          </Stack>
        )}

        {step === 2 && (
          <Stack spacing={2}>
            <Alert severity="info">
              Los planes son una <strong>simulación</strong> del proyecto: no se realiza ningún cobro ni se piden datos de pago.
            </Alert>
            {plans.map((plan) => (
              <Card
                key={plan.code}
                variant="outlined"
                sx={{ borderColor: plan.code === planCode ? 'primary.main' : 'divider', borderWidth: plan.code === planCode ? 2 : 1 }}
              >
                <CardActionArea onClick={() => setPlanCode(plan.code)} aria-pressed={plan.code === planCode}>
                  <CardContent>
                    <Stack direction="row" sx={{ justifyContent: 'space-between', gap: 1, flexWrap: 'wrap' }}>
                      <Typography variant="h6" component="h2">
                        {plan.name}
                      </Typography>
                      <Typography variant="body2" color="text.secondary">
                        {plan.price_label}
                      </Typography>
                    </Stack>
                    <Typography variant="body2" sx={{ mb: 1 }}>
                      {plan.description}
                    </Typography>
                    <Box component="ul" sx={{ pl: 3, m: 0 }}>
                      {plan.features.map((feature) => (
                        <Typography component="li" variant="body2" key={feature}>
                          {feature}
                        </Typography>
                      ))}
                    </Box>
                  </CardContent>
                </CardActionArea>
              </Card>
            ))}
            <Stack direction="row" spacing={1} sx={{ justifyContent: 'space-between' }}>
              <Button onClick={() => setStep(1)}>Atrás</Button>
              <Button variant="contained" onClick={submit} disabled={submitting}>
                {submitting ? 'Creando cuenta…' : 'Crear cuenta'}
              </Button>
            </Stack>
          </Stack>
        )}
      </Paper>
    </Layout>
  );
}
