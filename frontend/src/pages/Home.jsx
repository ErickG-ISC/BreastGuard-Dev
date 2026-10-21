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
            <Button component={RouterLink} to="/login" variant="contained" sx={{ alignSelf: 'start' }}>
              Iniciar sesión
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
