import { Stack, Typography } from '@mui/material';
import EventsLog from '../../components/admin/EventsLog';

// Bitácora administrativa de SU institución (el servidor impone el alcance)
export default function InstitutionLog() {
  return (
    <Stack spacing={2}>
      <Typography variant="h5" component="h1">
        Bitácora
      </Typography>
      <Typography variant="body2" color="text.secondary">
        Solo muestra la actividad administrativa de esta institución.
      </Typography>
      <EventsLog url="/institution/events" />
    </Stack>
  );
}
