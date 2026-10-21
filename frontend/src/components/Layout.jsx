import { AppBar, Box, Button, Container, Toolbar, Typography } from '@mui/material';
import { useAuth } from '../auth/AuthContext';

export const DISCLAIMER =
  'Herramienta de apoyo al diagnóstico. No sustituye el criterio ni la consulta médica.';

export default function Layout({ children }) {
  const { user, logout } = useAuth();

  return (
    <Box sx={{ minHeight: '100vh', bgcolor: 'background.default' }}>
      <AppBar position="static" elevation={0}>
        <Toolbar sx={{ gap: 1 }}>
          <Typography variant="h6" component="div" sx={{ flexGrow: 1 }}>
            BreastGuard
          </Typography>
          {user && (
            <Button color="inherit" onClick={logout}>
              Salir
            </Button>
          )}
        </Toolbar>
      </AppBar>
      <Container maxWidth="md" sx={{ py: 3, px: 2 }}>
        {children}
        <Typography variant="caption" color="text.secondary" component="p" sx={{ mt: 4 }}>
          {DISCLAIMER}
        </Typography>
      </Container>
    </Box>
  );
}
