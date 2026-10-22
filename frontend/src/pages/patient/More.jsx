import { Card, List, ListItemButton, ListItemIcon, ListItemText, Stack, Typography } from '@mui/material';
import { Link as RouterLink } from 'react-router-dom';
import { useAuth } from '../../auth/AuthContext';
import { ChevronRightIcon, LogoutIcon } from '../../components/icons';
import { SECONDARY_NAV } from '../../components/patientNav';

// Pestaña "Más" en móvil: las secciones que no caben en la barra inferior
export default function More() {
  const { logout } = useAuth();

  return (
    <Stack spacing={2}>
      <Typography variant="h5" component="h1">
        Más
      </Typography>
      <Card>
        <List disablePadding>
          {SECONDARY_NAV.map(({ label, to, icon: Icon }) => (
            <ListItemButton key={to} component={RouterLink} to={to} divider>
              <ListItemIcon>
                <Icon />
              </ListItemIcon>
              <ListItemText primary={label} />
              <ChevronRightIcon color="action" />
            </ListItemButton>
          ))}
          <ListItemButton onClick={logout}>
            <ListItemIcon>
              <LogoutIcon />
            </ListItemIcon>
            <ListItemText primary="Salir" />
          </ListItemButton>
        </List>
      </Card>
    </Stack>
  );
}
