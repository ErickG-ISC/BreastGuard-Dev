import { Card, CardContent, Stack, Typography } from '@mui/material';

// Marcador de la pestaña Diario mientras llega CU-04 (rama semana3-diario)
export default function Diary() {
  return (
    <Stack spacing={2}>
      <Typography variant="h5" component="h1">
        Diario
      </Typography>
      <Card>
        <CardContent>
          <Typography variant="body2">Muy pronto podrás registrar aquí cómo te sientes.</Typography>
        </CardContent>
      </Card>
    </Stack>
  );
}
