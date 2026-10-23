import { Alert, Box, Button, Card, CardContent, Chip, CircularProgress, Link, Stack, Typography } from '@mui/material';
import { useEffect, useState } from 'react';
import { Link as RouterLink, useParams } from 'react-router-dom';
import { api, errorMessage } from '../../api/client';
import SimpleMarkdown from '../../components/SimpleMarkdown';
import { TAG_LABELS, reviewLabel } from './blogLabels';

export default function BlogArticle() {
  const { slug } = useParams();
  const [article, setArticle] = useState(null);
  const [error, setError] = useState('');

  useEffect(() => {
    api
      .get(`/blog/${encodeURIComponent(slug)}`)
      .then(({ data }) => setArticle(data))
      .catch((err) => setError(errorMessage(err, 'No se encontró el artículo.')));
  }, [slug]);

  return (
    <Stack spacing={2}>
      <Button component={RouterLink} to="/informacion" sx={{ alignSelf: 'start' }}>
        ← Información
      </Button>
      {error && <Alert severity="error">{error}</Alert>}
      {!article && !error && <CircularProgress sx={{ alignSelf: 'center' }} />}
      {article && (
        <Card>
          <CardContent>
            <Stack spacing={1.5}>
              <Typography variant="h5" component="h1">
                {article.title}
              </Typography>
              <Stack direction="row" sx={{ flexWrap: 'wrap', gap: 0.5 }}>
                {article.tags.map((tag) => (
                  <Chip key={tag} size="small" label={TAG_LABELS[tag] ?? tag} />
                ))}
              </Stack>
              <Typography variant="caption" color="text.secondary">
                {reviewLabel(article)} · {article.reading_minutes} min de lectura
              </Typography>
              <SimpleMarkdown source={article.body} />
              {article.sources.length > 0 && (
                <Box>
                  <Typography variant="subtitle2" component="h2">
                    Fuentes
                  </Typography>
                  <Box component="ul" sx={{ pl: 2.5, my: 0.5 }}>
                    {article.sources.map((url) => (
                      <Typography component="li" variant="body2" key={url} sx={{ wordBreak: 'break-all' }}>
                        <Link href={url} target="_blank" rel="noopener noreferrer">
                          {url}
                        </Link>
                      </Typography>
                    ))}
                  </Box>
                </Box>
              )}
            </Stack>
          </CardContent>
        </Card>
      )}
    </Stack>
  );
}
