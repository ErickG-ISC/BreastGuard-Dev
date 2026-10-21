import { Button, Paper, Stack, Typography } from '@mui/material';
import { Link as RouterLink } from 'react-router-dom';
import { useAuth } from '../auth/AuthContext';
import Layout from '../components/Layout';

const ROLE_LABELS = {
  patient: 'Paciente',
  doctor: 'Médico',
  tenant_admin: 'Administración de la institución',
  platform_admin: 'Administración de la plataforma',
};

export default function Home() {
  const { user } = useAuth();

  return (
    <Layout>
      <Paper sx={{ p: 3 }}>
        <Stack spacing={2}>
          <Typography variant="h5" component="h1">
            Te damos la bienvenida a BreastGuard
          </Typography>
          {user ? (
            <Typography>
              Sesión iniciada como <strong>{ROLE_LABELS[user.role] ?? user.role}</strong>
              {user.tenant_slug ? ` en ${user.tenant_slug}` : ''}.
            </Typography>
          ) : (
            <Stack direction="row" spacing={1}>
              <Button component={RouterLink} to="/login" variant="contained">
                Iniciar sesión
              </Button>
              <Button component={RouterLink} to="/registro" variant="outlined">
                Crear cuenta
              </Button>
            </Stack>
          )}
          {user?.role === 'patient' && (
            <Button component={RouterLink} to="/paciente" variant="contained" sx={{ alignSelf: 'start' }}>
              Ir a tu espacio
            </Button>
          )}
          {user?.role === 'platform_admin' && (
            <Button component={RouterLink} to="/admin/tenants" variant="outlined" sx={{ alignSelf: 'start' }}>
              Administrar tenants
            </Button>
          )}
        </Stack>
      </Paper>
    </Layout>
  );
}
