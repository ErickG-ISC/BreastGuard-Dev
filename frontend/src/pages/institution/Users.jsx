import { Stack, Typography } from '@mui/material';
import StaffManager from '../../components/admin/StaffManager';

// Personal de la institución del tenant_admin. El tenant lo decide el servidor (JWT).
export default function InstitutionUsers() {
  return (
    <Stack spacing={2}>
      <Typography variant="h5" component="h1">
        Usuarios
      </Typography>
      <StaffManager
        listUrl="/institution/users"
        inviteUrl="/institution/users"
        userUrl={(id) => `/institution/users/${id}`}
        handoversUrl="/institution/handovers"
        handoverUrl={(id) => `/institution/handovers/${id}`}
      />
    </Stack>
  );
}
