import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControl,
  Grid,
  InputLabel,
  Link,
  List,
  ListItemButton,
  ListItemText,
  MenuItem,
  Select,
  Slider,
  Stack,
  TextField,
  Typography,
} from '@mui/material';
import { useCallback, useEffect, useRef, useState } from 'react';
import { Link as RouterLink, useParams } from 'react-router-dom';
import { api, errorMessage } from '../../api/client';
import { DISCLAIMER } from '../../components/Layout';
import {
  BIRADS,
  LATERALITY,
  NOTICED,
  ORIGIN,
  PROTOTYPE_WARNING,
  VIEW,
  SIDE,
  STATUS,
  SYMPTOM,
  ZONE,
  formatDate,
  formatDateTime,
  percent,
  resultColor,
  resultText,
} from './doctorLabels';

function Section({ title, children, action }) {
  return (
    <Card sx={{ height: '100%' }}>
      <CardContent>
        <Stack direction="row" sx={{ justifyContent: 'space-between', alignItems: 'center', mb: 1, gap: 1 }}>
          <Typography variant="h6" component="h2">
            {title}
          </Typography>
          {action}
        </Stack>
        {children}
      </CardContent>
    </Card>
  );
}

// Imagen con el mapa de calor superpuesto y su opacidad (D02, D03). URLs firmadas y cortas.
function Viewer({ analysis }) {
  const [opacity, setOpacity] = useState(50);
  if (!analysis) return <Typography color="text.secondary">Sin análisis.</Typography>;
  const meta = analysis.dicom_meta;
  return (
    <Stack spacing={1}>
      {analysis.prototype_warning && <Alert severity="warning">{analysis.prototype_warning}</Alert>}
      {/* Una mastografía es vertical: la altura se limita y el mapa de calor sigue a la imagen */}
      <Box sx={{ display: 'flex', justifyContent: 'center', bgcolor: 'imaging.main', borderRadius: 1, overflow: 'hidden' }}>
        <Box sx={{ position: 'relative', lineHeight: 0 }}>
          <Box
            component="img"
            src={analysis.image_url}
            alt={analysis.profile === 'mastografia_prototipo' ? 'Mastografía' : 'Ecografía'}
            sx={{ display: 'block', maxWidth: '100%', maxHeight: '70vh' }}
          />
          <Box
            component="img"
            src={analysis.heatmap_url}
            alt="Mapa de calor del modelo"
            sx={{ position: 'absolute', inset: 0, width: '100%', height: '100%', opacity: opacity / 100 }}
          />
        </Box>
      </Box>
      <Typography id="opacidad" variant="body2">
        Opacidad del mapa de calor
      </Typography>
      <Slider value={opacity} onChange={(_, v) => setOpacity(v)} aria-labelledby="opacidad" />
      <Stack direction="row" sx={{ gap: 1, flexWrap: 'wrap', alignItems: 'center' }}>
        <Chip color={resultColor(analysis)} label={resultText(analysis)} />
        <Typography variant="body2">Confianza {percent(analysis.confidence)}</Typography>
        <Typography variant="body2" color="text.secondary">
          Modelo {analysis.model_version}
        </Typography>
      </Stack>
      {meta && (
        <Typography variant="body2" color="text.secondary">
          DICOM {meta.modality ?? ''} · vista {VIEW[meta.view_position] ?? meta.view_position ?? '—'} · lateralidad{' '}
          {LATERALITY[meta.laterality] ?? meta.laterality ?? '—'} · {meta.columns}×{meta.rows} px
        </Typography>
      )}
      <Alert severity="info" variant="outlined">
        Apoyo al diagnóstico: el modelo orienta; la decisión clínica es de la médica.
      </Alert>
    </Stack>
  );
}

// Reporte técnico (D03): la categoría BI-RADS la asigna la médica; el modelo NO la sugiere.
function TechnicalReport({ analysis, onSave, busy, disabled }) {
  const [birads, setBirads] = useState(analysis.review?.birads ?? '');
  const [recommendation, setRecommendation] = useState(analysis.review?.recommendation ?? '');
  const review = analysis.review;
  return (
    <Stack spacing={2}>
      <Typography variant="body2">
        Modelo: <strong>{resultText(analysis)}</strong> · confianza {percent(analysis.confidence)} ·{' '}
        {analysis.model_version}
      </Typography>
      <FormControl size="small" sx={{ maxWidth: 360 }}>
        <InputLabel id={`birads-${analysis.id}`}>Categoría BI-RADS asignada por la médica</InputLabel>
        <Select
          labelId={`birads-${analysis.id}`}
          label="Categoría BI-RADS asignada por la médica"
          value={birads}
          onChange={(e) => setBirads(e.target.value)}
          disabled={disabled}
        >
          {BIRADS.map((b) => (
            <MenuItem key={b.value} value={b.value}>
              {b.label}
            </MenuItem>
          ))}
        </Select>
      </FormControl>
      <TextField
        label="Recomendación de la médica"
        multiline
        minRows={2}
        value={recommendation}
        onChange={(e) => setRecommendation(e.target.value)}
        disabled={disabled}
        slotProps={{ htmlInput: { maxLength: 2000 } }}
      />
      <Stack direction="row" sx={{ gap: 2, alignItems: 'center', flexWrap: 'wrap' }}>
        <Button
          variant="contained"
          disabled={!birads || busy || disabled}
          onClick={() => onSave({ birads, recommendation: recommendation.trim() || null })}
        >
          Guardar revisión
        </Button>
        {review && (
          <Typography variant="caption" color="text.secondary">
            Última revisión: {review.reviewed_by_name} · {formatDateTime(review.updated_at)}
          </Typography>
        )}
      </Stack>
      <Typography variant="caption" color="text.secondary">
        El modelo no asigna ni sugiere BI-RADS. La exportación a PDF y HL7 llega en la Semana 5.
      </Typography>
    </Stack>
  );
}

// Carga de estudios de la médica (D03): DICOM, JPG o PNG. El original DICOM nunca se guarda.
function StudyUpload({ onUpload, busy, disabled }) {
  const [file, setFile] = useState(null);
  const inputRef = useRef(null);
  async function submit(event) {
    event.preventDefault();
    if (await onUpload(file)) {
      setFile(null);
      if (inputRef.current) inputRef.current.value = '';
    }
  }
  return (
    <Stack spacing={2} component="form" onSubmit={submit}>
      <Alert severity="warning">{PROTOTYPE_WARNING}</Alert>
      <Button variant="outlined" component="label" disabled={busy || disabled} sx={{ alignSelf: 'flex-start' }}>
        Elegir archivo DICOM, JPG o PNG
        <input
          ref={inputRef}
          hidden
          type="file"
          accept=".dcm,.dicom,application/dicom,image/png,image/jpeg"
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
        />
      </Button>
      {file && (
        <Typography variant="body2" sx={{ wordBreak: 'break-all' }}>
          {file.name} · {(file.size / 1024 / 1024).toFixed(1)} MB
        </Typography>
      )}
      <Button type="submit" variant="contained" disabled={!file || busy || disabled} sx={{ alignSelf: 'flex-start' }}>
        {busy ? 'Analizando…' : 'Analizar estudio'}
      </Button>
      <Typography variant="caption" color="text.secondary">
        Se guarda solo una imagen derivada, sin datos personales. Máximo 60 MB y 4096 px por lado; JPEG Lossless no
        está soportado.
      </Typography>
    </Stack>
  );
}

function Notes({ notes, onAdd, onEdit, onDelete, busy }) {
  const [draft, setDraft] = useState('');
  const [editing, setEditing] = useState(null);

  async function submit(event) {
    event.preventDefault();
    if (await onAdd(draft)) setDraft('');
  }

  return (
    <Stack spacing={2}>
      <Stack spacing={1} component="form" onSubmit={submit}>
        <TextField
          label="Escribe una nota"
          multiline
          minRows={2}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          slotProps={{ htmlInput: { maxLength: 4000 } }}
        />
        <Button type="submit" variant="contained" disabled={!draft.trim() || busy} sx={{ alignSelf: 'flex-start' }}>
          Guardar nota
        </Button>
      </Stack>
      {!notes.length && <Typography color="text.secondary">Sin notas todavía.</Typography>}
      {notes.map((note) => (
        <Box key={note.id} sx={{ borderTop: 1, borderColor: 'divider', pt: 1 }}>
          <Typography variant="caption" color="text.secondary">
            {note.author_name} · {formatDateTime(note.created_at)}
            {note.updated_at && ` · editada ${formatDateTime(note.updated_at)}`}
          </Typography>
          <Typography sx={{ whiteSpace: 'pre-wrap' }}>{note.body}</Typography>
          {note.mine && (
            <Stack direction="row" spacing={1}>
              <Button size="small" onClick={() => setEditing({ id: note.id, body: note.body })} disabled={busy}>
                Editar
              </Button>
              <Button size="small" color="error" onClick={() => onDelete(note)} disabled={busy}>
                Borrar
              </Button>
            </Stack>
          )}
        </Box>
      ))}
      <Dialog open={Boolean(editing)} onClose={() => setEditing(null)} fullWidth maxWidth="sm">
        <DialogTitle>Editar nota</DialogTitle>
        <DialogContent>
          <TextField
            multiline
            minRows={3}
            fullWidth
            value={editing?.body ?? ''}
            onChange={(e) => setEditing({ ...editing, body: e.target.value })}
            slotProps={{ htmlInput: { maxLength: 4000, 'aria-label': 'Texto de la nota' } }}
            sx={{ mt: 1 }}
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setEditing(null)}>Cancelar</Button>
          <Button
            variant="contained"
            disabled={!editing?.body.trim() || busy}
            onClick={() => onEdit(editing).then((ok) => ok && setEditing(null))}
          >
            Guardar
          </Button>
        </DialogActions>
      </Dialog>
    </Stack>
  );
}

// CU-08: revisión de caso (D02). Las notas son solo de la médica; la paciente nunca las ve.
export default function Case() {
  const { id } = useParams();
  const [data, setData] = useState(null);
  const [error, setError] = useState('');
  const [message, setMessage] = useState(null);
  const [selected, setSelected] = useState(0);
  const [busy, setBusy] = useState(false);
  const busyRef = useRef(false);

  const load = useCallback(() => {
    api
      .get(`/doctor/patients/${id}`)
      .then(({ data: body }) => {
        setData(body);
        setError('');
      })
      .catch((err) => setError(errorMessage(err, 'No se pudo abrir el caso.')));
  }, [id]);

  useEffect(() => {
    load();
  }, [load]);

  async function run(request, success) {
    if (busyRef.current) return false;
    busyRef.current = true;
    setBusy(true);
    try {
      await request();
      if (success) setMessage({ severity: 'success', text: success });
      load();
      return true;
    } catch (err) {
      setMessage({ severity: 'error', text: errorMessage(err) });
      return false;
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  }

  const setStatus = (status, text) => run(() => api.patch(`/doctor/patients/${id}/status`, { status }), text);

  if (error) {
    return (
      <Stack spacing={2}>
        <Alert severity="error">{error}</Alert>
        <Button component={RouterLink} to="/medico" sx={{ alignSelf: 'flex-start' }}>
          Volver al panel
        </Button>
      </Stack>
    );
  }
  if (!data) return <CircularProgress sx={{ alignSelf: 'center' }} />;

  const analysis = data.analyses[selected];
  const examById = Object.fromEntries(data.self_exams.map((e) => [e.id, e]));
  const handoverBlocks = Boolean(data.handover_from);

  return (
    <Stack spacing={2}>
      <Typography variant="body2" color="text.secondary">
        <Link component={RouterLink} to="/medico">
          Panel
        </Link>{' '}
        › Caso
      </Typography>
      <Stack direction={{ xs: 'column', sm: 'row' }} sx={{ justifyContent: 'space-between', gap: 1 }}>
        <Box>
          <Typography variant="h5" component="h1">
            {data.display_name}
            {data.age_years != null && ` · ${data.age_years} años`}
          </Typography>
          <Typography variant="body2" color="text.secondary">
            {ORIGIN[data.origin]} el {formatDate(data.created_at)}
            {data.age_recorded_on && ` · edad registrada el ${formatDate(data.age_recorded_on)}`}
          </Typography>
        </Box>
        <Stack direction="row" sx={{ gap: 1, alignItems: 'center', flexWrap: 'wrap' }}>
          <Chip color={STATUS[data.status].color} label={STATUS[data.status].label} />
          {data.status === 'pendiente' && (
            <Button variant="outlined" disabled={busy || handoverBlocks} onClick={() => setStatus('en_revision')}>
              Empezar revisión
            </Button>
          )}
          {data.status !== 'revisado' ? (
            <Button
              variant="contained"
              disabled={busy || handoverBlocks}
              onClick={() => setStatus('revisado', 'Caso marcado como revisado.')}
            >
              Marcar revisado
            </Button>
          ) : (
            <Button variant="outlined" disabled={busy || handoverBlocks} onClick={() => setStatus('en_revision')}>
              Reabrir
            </Button>
          )}
        </Stack>
      </Stack>
      {data.status === 'revisado' && data.reviewed_at && (
        <Typography variant="body2" color="text.secondary">
          Revisado por {data.reviewed_by_name ?? 'una médica'} el {formatDateTime(data.reviewed_at)}
        </Typography>
      )}
      {handoverBlocks && (
        <Alert severity="warning">
          Esta paciente te llega por un traspaso de {data.handover_from}. Acéptalo en el panel para cambiar su estado.
        </Alert>
      )}
      {data.handover_to && <Alert severity="info">Hay un traspaso pendiente de tus pacientes a {data.handover_to}.</Alert>}
      {message && (
        <Alert severity={message.severity} onClose={() => setMessage(null)}>
          {message.text}
        </Alert>
      )}

      <Grid container spacing={2}>
        <Grid size={{ xs: 12, md: 4 }}>
          <Section title="Análisis">
            {!data.analyses.length && <Typography color="text.secondary">Sin análisis.</Typography>}
            <List dense disablePadding>
              {data.analyses.map((a, index) => (
                <ListItemButton key={a.id} selected={index === selected} onClick={() => setSelected(index)}>
                  <ListItemText primary={formatDateTime(a.created_at)} secondary={`Resultado: ${resultText(a)}`} />
                </ListItemButton>
              ))}
            </List>
          </Section>
        </Grid>
        <Grid size={{ xs: 12, md: 8 }}>
          <Section title="Imagen y mapa de calor">
            <Viewer key={analysis?.id} analysis={analysis} />
          </Section>
        </Grid>
        <Grid size={{ xs: 12, md: 6 }}>
          <Section title="Diario de síntomas (3 meses)">
            {!data.symptoms.length && <Typography color="text.secondary">Sin registros.</Typography>}
            <Stack spacing={1}>
              {data.symptoms.map((s) => {
                const exam = s.self_exam_id ? examById[s.self_exam_id] : null;
                return (
                  <Box key={s.id} sx={{ borderTop: 1, borderColor: 'divider', pt: 1 }}>
                    <Typography variant="body2">
                      <strong>{formatDate(s.entry_date)}</strong> · {s.symptoms.map((c) => SYMPTOM[c] ?? c).join(', ')} ·{' '}
                      {SIDE[s.side]}, {ZONE[s.zone]} · intensidad {s.intensity}/10
                    </Typography>
                    {exam && (
                      <Typography variant="caption" color="text.secondary">
                        Ligado a la autoexploración del {formatDate(exam.started_at)}: {NOTICED[exam.noticed_change] ?? '—'}
                      </Typography>
                    )}
                    {s.note && <Typography variant="body2" color="text.secondary">{s.note}</Typography>}
                  </Box>
                );
              })}
            </Stack>
          </Section>
        </Grid>
        <Grid size={{ xs: 12, md: 6 }}>
          <Section title="Cuestionario">
            {!data.questionnaire ? (
              <Typography color="text.secondary">No compartió el cuestionario.</Typography>
            ) : (
              <Stack spacing={1}>
                <Typography variant="body2" color="text.secondary">
                  Respondido el {formatDate(data.questionnaire.created_at)} · versión {data.questionnaire.version}
                </Typography>
                {data.questionnaire.risk_factors.length ? (
                  <Box component="ul" sx={{ pl: 2, m: 0 }}>
                    {data.questionnaire.risk_factors.map((f, i) => (
                      <Typography component="li" variant="body2" key={i}>
                        {typeof f === 'string' ? f : (f.label ?? f.code ?? JSON.stringify(f))}
                      </Typography>
                    ))}
                  </Box>
                ) : (
                  <Typography variant="body2">Sin factores a comentar.</Typography>
                )}
              </Stack>
            )}
          </Section>
        </Grid>
        <Grid size={{ xs: 12, md: 6 }}>
          <Section title="Notas de la médica">
            <Notes
              notes={data.notes}
              busy={busy}
              onAdd={(body) => run(() => api.post(`/doctor/patients/${id}/notes`, { body }), 'Nota guardada.')}
              onEdit={(note) => run(() => api.patch(`/doctor/notes/${note.id}`, { body: note.body }), 'Nota actualizada.')}
              onDelete={(note) => run(() => api.delete(`/doctor/notes/${note.id}`), 'Nota borrada.')}
            />
          </Section>
        </Grid>
        <Grid size={{ xs: 12, md: 6 }}>
          {/* CU-09: estudios de la médica y reporte técnico con BI-RADS de la médica */}
          <Section title="Agregar estudio">
            <StudyUpload
              busy={busy}
              disabled={handoverBlocks}
              onUpload={(file) => {
                const form = new FormData();
                form.append('file', file);
                return run(
                  () => api.post(`/doctor/patients/${id}/analyses`, form).then(() => setSelected(0)),
                  'Estudio analizado. El caso vuelve a pendiente.',
                );
              }}
            />
          </Section>
        </Grid>
        <Grid size={{ xs: 12 }}>
          <Section title="Reporte técnico">
            {!analysis ? (
              <Typography color="text.secondary">Elige un análisis para revisarlo.</Typography>
            ) : (
              <TechnicalReport
                key={`${analysis.id}-${analysis.review?.updated_at ?? ''}`}
                analysis={analysis}
                busy={busy}
                disabled={handoverBlocks}
                onSave={(review) =>
                  run(() => api.put(`/doctor/analyses/${analysis.id}/review`, review), 'Revisión guardada.')
                }
              />
            )}
          </Section>
        </Grid>
      </Grid>
      <Typography variant="caption" color="text.secondary" component="p">
        {DISCLAIMER}
      </Typography>
    </Stack>
  );
}
