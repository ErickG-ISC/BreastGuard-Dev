import { Alert, Button, Stack, Typography } from '@mui/material';
import { useState } from 'react';
import { Navigate, Link as RouterLink } from 'react-router-dom';
import { useAuth } from '../auth/AuthContext';
import Layout from '../components/Layout';

export const PENDING_CODE_KEY = 'pending_import_code';

// Guarda el código del fragmento y lo quita de la barra y del historial (idempotente)
function captureCode() {
  const code = new URLSearchParams(window.location.hash.slice(1)).get('c');
  if (code) {
    try {
      sessionStorage.setItem(PENDING_CODE_KEY, code);
    } catch {
      // sin almacenamiento: la médica tendrá que escribir el código
    }
    window.history.replaceState(null, '', window.location.pathname);
  }
  try {
    return Boolean(code || sessionStorage.getItem(PENDING_CODE_KEY));
  } catch {
    return Boolean(code);
  }
}

// Destino del enlace que comparte la paciente: PUBLIC_APP_URL/importar#c=CÓDIGO.
// El código viaja en el fragmento (nunca llega al servidor). Aquí se guarda en sessionStorage,
// se borra de la barra y del historial, y se manda a la médica a iniciar sesión e importar.
export default function ImportLink() {
  const { user, loading } = useAuth();
  const [hasCode] = useState(captureCode);

  if (!loading && user?.role === 'doctor') return <Navigate to="/medico/importar" replace />;

  return (
    <Layout>
      <Stack spacing={2}>
        <Typography variant="h5" component="h1">
          Importar un paquete compartido
        </Typography>
        {user && user.role !== 'doctor' ? (
          <Alert severity="info">Solo una médica con cuenta en BreastGuard puede importar este paquete.</Alert>
        ) : (
          <>
            <Typography>
              {hasCode
                ? 'Inicia sesión con tu cuenta de médica para importar la copia en tu institución.'
                : 'Inicia sesión con tu cuenta de médica y escribe el código que te dio tu paciente.'}
            </Typography>
            <Button variant="contained" component={RouterLink} to="/login" sx={{ alignSelf: 'flex-start' }}>
              Iniciar sesión
            </Button>
          </>
        )}
      </Stack>
    </Layout>
  );
}
