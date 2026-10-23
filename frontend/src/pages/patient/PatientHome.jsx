import { Alert, Box, Button, Card, CardContent, Chip, Stack, Typography } from '@mui/material';
import { useEffect, useState } from 'react';
import { Link as RouterLink } from 'react-router-dom';
import { api } from '../../api/client';
import { NOTICE_TEXT, useNotices } from '../../notices/NoticesContext';
import { DISCLAIMER } from '../../components/Layout';
import { QuestionnaireResult } from './Questionnaire';

export function ImageGuide() {
  return (
    <Card variant="outlined">
      <CardContent>
        <Typography variant="h6" component="h2" sx={{ mb: 1 }}>
          ¿Qué imágenes puedo subir?
        </Typography>
        <Typography variant="body2" component="div">
          <Box component="ul" sx={{ pl: 2.5, m: 0 }}>
            <li>
              <strong>Ecografías (ultrasonido) de mama</strong>, como las que entrega la clínica en JPG o PNG. El modelo se
              entrenó con ecografías tipo BUSI.
            </li>
            <li>Una imagen por análisis, en escala de grises, sin recortes extremos.</li>
            <li>
              <strong>No</strong> subas mastografías, fotos de la piel ni fotos a color: el resultado no sería válido y la
              aplicación las rechazará.
            </li>
            <li>Usa solo imágenes tuyas o de las que tengas autorización.</li>
          </Box>
        </Typography>
        <Alert severity="warning" sx={{ mt: 2 }}>
          {DISCLAIMER}
        </Alert>
      </CardContent>
    </Card>
  );
}

function NoticeCards() {
  const { notices, markRead } = useNotices();
  return notices.slice(0, 2).map((notice) => {
    const text = NOTICE_TEXT[notice.kind];
    return (
      <Alert
        key={notice.id}
        severity="info"
        action={
          <Button component={RouterLink} to={text.to} onClick={() => markRead(notice.id)} size="small">
            {text.action}
          </Button>
        }
      >
        {text.title}
      </Alert>
    );
  });
}

export default function PatientHome() {
  const [subscription, setSubscription] = useState(null);
  const [questionnaire, setQuestionnaire] = useState(undefined);

  useEffect(() => {
    api.get('/subscription/me').then(({ data }) => setSubscription(data)).catch(() => setSubscription(null));
    api
      .get('/questionnaires/latest')
      .then(({ data }) => setQuestionnaire(data))
      .catch(() => setQuestionnaire(null));
  }, []);

  return (
    <>
      <Stack spacing={2}>
        <Stack direction="row" sx={{ alignItems: 'center', justifyContent: 'space-between', gap: 1, flexWrap: 'wrap' }}>
          <Typography variant="h5" component="h1">
            Tu espacio
          </Typography>
          {subscription && <Chip label={`Plan ${subscription.plan.name} (simulado)`} />}
        </Stack>

        <NoticeCards />

        <Card variant="outlined">
          <CardContent>
            <Typography variant="h6" component="h2" sx={{ mb: 1 }}>
              Analizar una ecografía
            </Typography>
            <Typography variant="body2" sx={{ mb: 2 }}>
              Sube una ecografía mamaria y recibe un resultado orientativo con un mapa de las zonas que el modelo observó.
            </Typography>
            <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1}>
              <Button component={RouterLink} to="/analizar" variant="contained">
                Subir ecografía
              </Button>
              <Button component={RouterLink} to="/historial">
                Ver historial
              </Button>
            </Stack>
          </CardContent>
        </Card>

        <Card variant="outlined">
          <CardContent>
            <Typography variant="h6" component="h2" sx={{ mb: 1 }}>
              Autoexploración guiada
            </Typography>
            <Typography variant="body2" sx={{ mb: 2 }}>
              Conoce cómo se ven y se sienten normalmente tus mamas para notar cualquier cambio. Te guiamos paso a paso.
            </Typography>
            <Button component={RouterLink} to="/autoexploracion" variant="outlined">
              Comenzar autoexploración
            </Button>
          </CardContent>
        </Card>

        <Card variant="outlined">
          <CardContent>
            <Typography variant="h6" component="h2" sx={{ mb: 1 }}>
              Tus antecedentes
            </Typography>
            {questionnaire ? (
              <QuestionnaireResult result={questionnaire} />
            ) : (
              questionnaire === null && (
                <Typography variant="body2" sx={{ mb: 1 }}>
                  Aún no respondes el cuestionario de antecedentes.
                </Typography>
              )
            )}
            <Button component={RouterLink} to="/cuestionario" sx={{ mt: 1 }}>
              {questionnaire ? 'Actualizar respuestas' : 'Responder cuestionario'}
            </Button>
          </CardContent>
        </Card>

        <ImageGuide />
      </Stack>
    </>
  );
}
