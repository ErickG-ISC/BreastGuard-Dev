import {
  AppBar,
  Box,
  Container,
  Divider,
  Drawer,
  IconButton,
  List,
  ListItemButton,
  ListItemIcon,
  ListItemText,
  Toolbar,
  Typography,
  useMediaQuery,
} from '@mui/material';
import { useState } from 'react';
import { Link as RouterLink, Outlet, useLocation } from 'react-router-dom';
import { useAuth } from '../auth/AuthContext';
import { LogoutIcon, MoreIcon } from './icons';

const DRAWER_WIDTH = 260;

// Estructura de las pantallas de administración (wireframe D04): barra lateral fija en
// escritorio y cajón con botón de menú en móvil. `items`: [{ label, to, icon }].
export default function AdminShell({ title, items }) {
  const { logout } = useAuth();
  const { pathname } = useLocation();
  const desktop = useMediaQuery((theme) => theme.breakpoints.up('md'));
  const [open, setOpen] = useState(false);

  const nav = (
    <Box sx={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <Toolbar sx={{ flexDirection: 'column', alignItems: 'flex-start', justifyContent: 'center' }}>
        <Typography variant="h6" component="div" color="primary">
          BreastGuard
        </Typography>
        <Typography variant="caption" color="text.secondary">
          {title}
        </Typography>
      </Toolbar>
      <Divider />
      <List component="nav" aria-label="Administración">
        {items.map(({ label, to, icon: Icon }) => (
          <ListItemButton
            key={to}
            component={RouterLink}
            to={to}
            selected={pathname === to || pathname.startsWith(`${to}/`)}
            onClick={() => setOpen(false)}
            sx={{ borderRadius: 2, mx: 1 }}
          >
            <ListItemIcon sx={{ minWidth: 40 }}>
              <Icon />
            </ListItemIcon>
            <ListItemText primary={label} />
          </ListItemButton>
        ))}
      </List>
      <Box sx={{ flexGrow: 1 }} />
      <List>
        <ListItemButton onClick={logout} sx={{ borderRadius: 2, mx: 1 }}>
          <ListItemIcon sx={{ minWidth: 40 }}>
            <LogoutIcon />
          </ListItemIcon>
          <ListItemText primary="Salir" />
        </ListItemButton>
      </List>
    </Box>
  );

  return (
    <Box sx={{ display: 'flex', minHeight: '100vh', bgcolor: 'background.default' }}>
      {desktop ? (
        <Drawer
          variant="permanent"
          sx={{ width: DRAWER_WIDTH, flexShrink: 0, '& .MuiDrawer-paper': { width: DRAWER_WIDTH } }}
        >
          {nav}
        </Drawer>
      ) : (
        <Drawer open={open} onClose={() => setOpen(false)} sx={{ '& .MuiDrawer-paper': { width: DRAWER_WIDTH } }}>
          {nav}
        </Drawer>
      )}
      <Box sx={{ flexGrow: 1, minWidth: 0 }}>
        {!desktop && (
          <AppBar position="sticky" sx={{ borderBottom: 1, borderColor: 'divider' }}>
            <Toolbar sx={{ gap: 1 }}>
              <IconButton edge="start" aria-label="Abrir menú" onClick={() => setOpen(true)}>
                <MoreIcon />
              </IconButton>
              <Typography variant="h6" component="div" color="primary">
                BreastGuard
              </Typography>
            </Toolbar>
          </AppBar>
        )}
        <Container component="main" maxWidth="lg" sx={{ py: 3, px: 2 }}>
          <Outlet />
        </Container>
      </Box>
    </Box>
  );
}
