import {
  AppBar,
  BottomNavigation,
  BottomNavigationAction,
  Box,
  Button,
  Container,
  Divider,
  Drawer,
  List,
  ListItemButton,
  ListItemIcon,
  ListItemText,
  Paper,
  Toolbar,
  Typography,
  useMediaQuery,
} from '@mui/material';
import { Link as RouterLink, Outlet, useLocation } from 'react-router-dom';
import { useAuth } from '../auth/AuthContext';
import { LogoutIcon } from './icons';
import { DISCLAIMER } from './Layout';
import { PRIMARY_NAV, SECONDARY_NAV, activePrimary, isActive } from './patientNav';

const DRAWER_WIDTH = 240;

function SideNav({ pathname, onLogout }) {
  const item = (entry) => {
    const Icon = entry.icon;
    // En escritorio "Más" sobra: sus secciones se listan directamente
    if (entry.to === '/mas') return null;
    return (
      <ListItemButton
        key={entry.to}
        component={RouterLink}
        to={entry.to}
        selected={isActive(entry, pathname)}
        sx={{ borderRadius: 2, mx: 1 }}
      >
        <ListItemIcon sx={{ minWidth: 40 }}>
          <Icon />
        </ListItemIcon>
        <ListItemText primary={entry.label} />
      </ListItemButton>
    );
  };

  return (
    <Drawer
      variant="permanent"
      sx={{
        width: DRAWER_WIDTH,
        flexShrink: 0,
        '& .MuiDrawer-paper': { width: DRAWER_WIDTH, boxSizing: 'border-box' },
      }}
    >
      <Toolbar>
        <Typography variant="h6" component="div" color="primary">
          BreastGuard
        </Typography>
      </Toolbar>
      <Box component="nav" aria-label="Secciones">
        <List>{PRIMARY_NAV.map(item)}</List>
        <Divider sx={{ my: 1 }} />
        <List>{SECONDARY_NAV.map(item)}</List>
      </Box>
      <Box sx={{ flexGrow: 1 }} />
      <List>
        <ListItemButton onClick={onLogout} sx={{ borderRadius: 2, mx: 1 }}>
          <ListItemIcon sx={{ minWidth: 40 }}>
            <LogoutIcon />
          </ListItemIcon>
          <ListItemText primary="Salir" />
        </ListItemButton>
      </List>
    </Drawer>
  );
}

function BottomNav({ pathname }) {
  return (
    <Paper
      component="nav"
      aria-label="Secciones"
      square
      elevation={3}
      sx={{ position: 'fixed', bottom: 0, left: 0, right: 0, zIndex: 'appBar', pb: 'env(safe-area-inset-bottom)' }}
    >
      <BottomNavigation showLabels value={activePrimary(pathname)}>
        {PRIMARY_NAV.map(({ label, to, icon: Icon }) => (
          <BottomNavigationAction key={to} label={label} value={to} icon={<Icon />} component={RouterLink} to={to} />
        ))}
      </BottomNavigation>
    </Paper>
  );
}

// Estructura de la app de paciente: barra inferior en móvil y barra lateral en escritorio
export default function PatientShell() {
  const { logout } = useAuth();
  const { pathname } = useLocation();
  const desktop = useMediaQuery((theme) => theme.breakpoints.up('md'));

  return (
    <Box sx={{ display: 'flex', minHeight: '100vh', bgcolor: 'background.default' }}>
      {desktop && <SideNav pathname={pathname} onLogout={logout} />}
      <Box sx={{ flexGrow: 1, minWidth: 0 }}>
        {!desktop && (
          <AppBar position="sticky" sx={{ borderBottom: 1, borderColor: 'divider' }}>
            <Toolbar sx={{ gap: 1 }}>
              <Typography variant="h6" component="div" color="primary" sx={{ flexGrow: 1 }}>
                BreastGuard
              </Typography>
              <Button onClick={logout}>Salir</Button>
            </Toolbar>
          </AppBar>
        )}
        <Container component="main" maxWidth="md" sx={{ py: 3, px: 2, pb: desktop ? 4 : 12 }}>
          <Outlet />
          <Typography variant="caption" color="text.secondary" component="p" sx={{ mt: 4 }}>
            {DISCLAIMER}
          </Typography>
        </Container>
      </Box>
      {!desktop && <BottomNav pathname={pathname} />}
    </Box>
  );
}
