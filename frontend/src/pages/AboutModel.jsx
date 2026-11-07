import {
  Alert,
  CircularProgress,
  Paper,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Typography,
} from '@mui/material';
import { useEffect, useState } from 'react';
import { api, errorMessage } from '../api/client';
import Layout from '../components/Layout';

// "Acerca del modelo" (pública, ADR 0014). Muestra SOLO lo que trae la ficha del modelo cargado:
// si un dato no está, no aparece. Nunca se inventan métricas.
const CLASS = { normal: 'Normal', benigno: 'Benigno', maligno: 'Maligno' };
const TRAINING = {
  dataset: 'Datos de entrenamiento',
  images: 'Imágenes',
  patients: 'Pacientes',
  split: 'División',
  split_by_patient: 'División por paciente (sin fuga entre conjuntos)',
  trained_on: 'Fecha de entrenamiento',
  architecture: 'Arquitectura',
};
const METRIC = {
  accuracy: 'Exactitud',
  balanced_accuracy: 'Exactitud balanceada',
  auc: 'AUC',
  ece_before: 'Error de calibración (ECE) antes de calibrar',
  ece_after: 'Error de calibración (ECE) después de calibrar',
  sensitivity: 'Sensibilidad',
  specificity: 'Especificidad',
  precision: 'Precisión',
  f1: 'F1',
  support: 'Casos',
};

function label(map, key) {
  return map[key] ?? key.replaceAll('_', ' ');
}

function value(v) {
  if (typeof v === 'boolean') return v ? 'Sí' : 'No';
  if (typeof v === 'number' && v > 0 && v < 1) return v.toFixed(3);
  return String(v);
}

function Section({ title, children }) {
  return (
    <Paper sx={{ p: { xs: 2, sm: 3 } }}>
      <Stack spacing={1.5}>
        <Typography variant="h6" component="h2">
          {title}
        </Typography>
        {children}
      </Stack>
    </Paper>
  );
}

function KeyValues({ data, map }) {
  return (
    <Stack component="dl" spacing={0.5} sx={{ m: 0 }}>
      {Object.entries(data).map(([k, v]) => (
        <Typography variant="body2" key={k}>
          <Typography component="dt" variant="body2" sx={{ display: 'inline', fontWeight: 600 }}>
            {label(map, k)}:
          </Typography>{' '}
          <Typography component="dd" variant="body2" sx={{ display: 'inline', m: 0 }}>
            {value(v)}
          </Typography>
        </Typography>
      ))}
    </Stack>
  );
}

function ConfusionMatrix({ matrix, classes }) {
  return (
    <TableContainer>
      <Table size="small" aria-label="Matriz de confusión">
        <TableHead>
          <TableRow>
            <TableCell>Real \ Predicha</TableCell>
            {classes.map((c) => (
              <TableCell key={c} align="right">
                {CLASS[c] ?? c}
              </TableCell>
            ))}
          </TableRow>
        </TableHead>
        <TableBody>
          {matrix.map((row, i) => (
            <TableRow key={classes[i]}>
              <TableCell component="th" scope="row">
                {CLASS[classes[i]] ?? classes[i]}
              </TableCell>
              {row.map((n, j) => (
                <TableCell key={classes[j]} align="right">
                  {n}
                </TableCell>
              ))}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </TableContainer>
  );
}

function Metrics({ metrics, classes }) {
  const { confusion_matrix: matrix, per_class: perClass, test_set: testSet, ...overall } = metrics;
  return (
    <Section title="Métricas en el conjunto de prueba">
      {testSet && <Typography variant="body2">Conjunto de prueba: {testSet}</Typography>}
      {Object.keys(overall).length > 0 && <KeyValues data={overall} map={METRIC} />}
      {perClass &&
        Object.entries(perClass).map(([c, values]) => (
          <Stack key={c} spacing={0.5}>
            <Typography variant="subtitle2">{CLASS[c] ?? c}</Typography>
            <KeyValues data={values} map={METRIC} />
          </Stack>
        ))}
      {matrix && <ConfusionMatrix matrix={matrix} classes={classes} />}
    </Section>
  );
}

export default function AboutModel() {
  const [card, setCard] = useState(null);
  const [error, setError] = useState('');

  useEffect(() => {
    api
      .get('/model/card')
      .then(({ data }) => setCard(data))
      .catch((err) => setError(errorMessage(err, 'No se pudo cargar la información del modelo.')));
  }, []);

  return (
    <Layout>
      <Stack spacing={2}>
        <Typography variant="h5" component="h1">
          Acerca del modelo
        </Typography>
        {error && <Alert severity="error">{error}</Alert>}
        {!card && !error && <CircularProgress aria-label="Cargando" />}
        {card && (
          <>
            <Alert severity="warning">{card.mammography_warning}</Alert>
            {card.status !== 'loaded' ? (
              <Alert severity="info">El modelo no está disponible en este momento.</Alert>
            ) : (
              <>
                {card.is_demo && (
                  <Alert severity="info">
                    Modelo de demostración sin entrenar: sus resultados no tienen validez y no hay métricas.
                  </Alert>
                )}
                <Section title="Modelo">
                  <Typography variant="body2">Versión: {card.model_version}</Typography>
                  <Typography variant="body2">
                    Clases: {card.classes.map((c) => CLASS[c] ?? c).join(', ')}
                  </Typography>
                  {card.description && <Typography variant="body2">{card.description}</Typography>}
                  {card.intended_use && (
                    <Typography variant="body2">Uso previsto: {card.intended_use}</Typography>
                  )}
                  <Typography variant="body2">
                    {card.calibrated
                      ? `Confianza calibrada (escalado por temperatura, T = ${card.calibration.temperature}).`
                      : 'La confianza que se muestra es la salida directa del modelo, sin calibrar.'}
                  </Typography>
                </Section>
                {card.training && (
                  <Section title="Datos de entrenamiento">
                    <KeyValues data={card.training} map={TRAINING} />
                  </Section>
                )}
                {card.metrics && <Metrics metrics={card.metrics} classes={card.classes} />}
                {card.limitations && (
                  <Section title="Limitaciones">
                    <Stack component="ul" spacing={0.5} sx={{ m: 0, pl: 3 }}>
                      {card.limitations.map((item) => (
                        <Typography component="li" variant="body2" key={item}>
                          {item}
                        </Typography>
                      ))}
                    </Stack>
                  </Section>
                )}
              </>
            )}
            <Typography variant="body2" color="text.secondary">
              {card.disclaimer}
            </Typography>
          </>
        )}
      </Stack>
    </Layout>
  );
}
