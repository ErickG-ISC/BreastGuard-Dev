import { Stack, Typography } from '@mui/material';
import { useEffect, useState } from 'react';
import { api } from '../../api/client';
import EventsLog from '../../components/admin/EventsLog';

// Bitácora de plataforma completa (solo platform_admin)
export default function PlatformLog() {
  const [names, setNames] = useState({});

  useEffect(() => {
    api
      .get('/admin/tenants', { params: { limit: 100 } })
      .then(({ data }) => setNames(Object.fromEntries(data.items.map((t) => [t.id, t.name]))))
      .catch(() => setNames({}));
  }, []);

  return (
    <Stack spacing={2}>
      <Typography variant="h5" component="h1">
        Auditoría de plataforma
      </Typography>
      <Typography variant="body2" color="text.secondary">
        Cambios administrativos de todas las instituciones: quién, qué, cuándo y desde dónde. Sin datos clínicos.
      </Typography>
      <EventsLog url="/admin/events" tenants={names} />
    </Stack>
  );
}
