import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Alert,
  Box,
  Card,
  CardActionArea,
  CardContent,
  Chip,
  CircularProgress,
  InputAdornment,
  Stack,
  TextField,
  Typography,
} from '@mui/material';
import { useEffect, useMemo, useState } from 'react';
import { Link as RouterLink } from 'react-router-dom';
import { api, errorMessage } from '../../api/client';
import { InfoIcon, SearchIcon } from '../../components/icons';
import SimpleMarkdown from '../../components/SimpleMarkdown';
import { TAG_LABELS, recommendedTag, reviewLabel } from './blogLabels';

// Quita acentos y mayúsculas para buscar "ecografia" o "Ecografía" por igual
const normalize = (text) => text.normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();

function ArticleCard({ article, featured = false }) {
  return (
    <Card>
      <CardActionArea component={RouterLink} to={`/informacion/${article.slug}`}>
        {featured && (
          <Box
            sx={{ height: 96, bgcolor: 'action.hover', display: 'flex', alignItems: 'center', justifyContent: 'center' }}
          >
            <InfoIcon color="primary" sx={{ fontSize: 40 }} />
          </Box>
        )}
        <CardContent>
          <Typography variant="subtitle1" component="h3" sx={{ fontWeight: 600 }}>
            {article.title}
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ my: 0.5 }}>
            {article.summary}
          </Typography>
          <Typography variant="caption" color="text.secondary">
            {reviewLabel(article)} · {article.reading_minutes} min
          </Typography>
        </CardContent>
      </CardActionArea>
    </Card>
  );
}

function Faq({ body }) {
  // Cada "## pregunta" del markdown es una pregunta; lo que sigue es su respuesta
  const items = body
    .split(/^## /m)
    .filter((chunk) => chunk.trim())
    .map((chunk) => {
      const [question, ...rest] = chunk.split('\n');
      return { question: question.trim(), answer: rest.join('\n').trim() };
    });
  return (
    <Box>
      {items.map((item) => (
        <Accordion key={item.question} disableGutters variant="outlined">
          <AccordionSummary>
            <Typography variant="body1">{item.question}</Typography>
          </AccordionSummary>
          <AccordionDetails>
            <SimpleMarkdown source={item.answer} />
          </AccordionDetails>
        </Accordion>
      ))}
    </Box>
  );
}

export default function Blog() {
  const [articles, setArticles] = useState(null);
  const [faq, setFaq] = useState(null);
  const [lastAnalysis, setLastAnalysis] = useState(undefined);
  const [query, setQuery] = useState('');
  const [tag, setTag] = useState('');
  const [error, setError] = useState('');

  useEffect(() => {
    api
      .get('/blog')
      .then(({ data }) => setArticles(data))
      .catch((err) => setError(errorMessage(err, 'No se pudo cargar el contenido.')));
    api
      .get('/blog/faq')
      .then(({ data }) => setFaq(data))
      .catch(() => setFaq(null));
    api
      .get('/analyses', { params: { limit: 1 } })
      .then(({ data }) => setLastAnalysis(data.items[0] ?? null))
      .catch(() => setLastAnalysis(null));
  }, []);

  const tags = useMemo(() => [...new Set((articles ?? []).flatMap((a) => a.tags))], [articles]);
  const visible = useMemo(() => {
    const q = normalize(query.trim());
    return (articles ?? []).filter(
      (a) =>
        (!tag || a.tags.includes(tag)) &&
        (!q || normalize(`${a.title} ${a.summary} ${a.tags.join(' ')}`).includes(q)),
    );
  }, [articles, query, tag]);
  const recommended =
    articles && lastAnalysis !== undefined
      ? articles.find((a) => a.tags.includes(recommendedTag(lastAnalysis)))
      : null;
  const filtering = query.trim() || tag;

  return (
    <Stack spacing={2}>
      <Typography variant="h5" component="h1">
        Información
      </Typography>
      <TextField
        placeholder="Buscar artículos…"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        slotProps={{
          htmlInput: { 'aria-label': 'Buscar artículos' },
          input: {
            startAdornment: (
              <InputAdornment position="start">
                <SearchIcon fontSize="small" />
              </InputAdornment>
            ),
          },
        }}
      />
      <Stack direction="row" sx={{ flexWrap: 'wrap', gap: 1 }}>
        <Chip label="Todos" color={tag ? 'default' : 'primary'} onClick={() => setTag('')} aria-pressed={!tag} />
        {tags.map((code) => (
          <Chip
            key={code}
            label={TAG_LABELS[code] ?? code}
            color={tag === code ? 'primary' : 'default'}
            variant={tag === code ? 'filled' : 'outlined'}
            onClick={() => setTag(tag === code ? '' : code)}
            aria-pressed={tag === code}
          />
        ))}
      </Stack>
      {error && <Alert severity="error">{error}</Alert>}
      {!articles && !error && <CircularProgress sx={{ alignSelf: 'center' }} />}

      {recommended && !filtering && (
        <Box>
          <Typography variant="h6" component="h2" sx={{ mb: 1 }}>
            Recomendado para ti
          </Typography>
          <ArticleCard article={recommended} featured />
        </Box>
      )}

      {articles && (
        <Stack spacing={1.5}>
          {filtering && (
            <Typography variant="body2" color="text.secondary">
              {visible.length} resultado{visible.length === 1 ? '' : 's'}
            </Typography>
          )}
          {visible
            .filter((a) => filtering || a.slug !== recommended?.slug)
            .map((article) => (
              <ArticleCard key={article.slug} article={article} />
            ))}
        </Stack>
      )}

      {faq && !filtering && (
        <Box>
          <Typography variant="h6" component="h2" sx={{ mb: 1 }}>
            Preguntas frecuentes
          </Typography>
          <Faq body={faq.body} />
        </Box>
      )}
    </Stack>
  );
}
