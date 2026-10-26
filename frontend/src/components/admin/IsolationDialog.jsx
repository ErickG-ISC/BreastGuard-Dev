import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  List,
  ListItem,
  ListItemText,
  Stack,
  Typography,
} from '@mui/material';
import { useEffect, useState } from 'react';
import { api, errorMessage } from '../../api/client';

const CHECKS = [
  ['app_role_without_bypass', 'La app se conecta sin superusuario ni BYPASSRLS', (r) => r.app_role_without_bypass],
  ['rows_visible_without_context', 'Sin contexto de tenant se ven 0 filas', (r) => r.rows_visible_without_context === 0],
  ['foreign_rows_visible_to_tenant', 'El tenant ve 0 filas de otros tenants', (r) => r.foreign_rows_visible_to_tenant === 0],
  ['tenant_rows_visible_to_others', 'Los demás tenants ven 0 filas de este', (r) => r.tenant_rows_visible_to_others === 0],
  ['conclusive', 'Prueba concluyente (hay filas testigo y otros tenants)', (r) => r.conclusive],
];

// Chequeo de aislamiento (CU-12): se ejecuta como el rol de la app y solo devuelve conteos.
// El padre le pone `key` por tenant para no arrastrar el resultado anterior.
export default function IsolationDialog({ tenant, onClose }) {
  const [report, setReport] = useState(null);
  const [error, setError] = useState('');
  const [run, setRun] = useState(0);

  useEffect(() => {
    if (!tenant) return;
    api
      .post(`/admin/tenants/${tenant.id}/isolation-check`)
      .then(({ data }) => {
        setReport(data);
        setError('');
      })
      .catch((err) => setError(errorMessage(err, 'No se pudo ejecutar el chequeo.')));
  }, [tenant, run]);

  return (
    <Dialog open={Boolean(tenant)} onClose={onClose} fullWidth maxWidth="sm">
      <DialogTitle>Chequeo de aislamiento: {tenant?.slug}</DialogTitle>
      <DialogContent>
        {error && <Alert severity="error">{error}</Alert>}
        {!report && !error && (
          <Box sx={{ display: 'flex', justifyContent: 'center', py: 3 }}>
            <CircularProgress />
          </Box>
        )}
        {report && (
          <Stack spacing={2}>
            <Alert severity={report.passed ? 'success' : 'error'}>
              {report.passed ? 'Aislamiento verificado' : 'El chequeo NO pasó'}
            </Alert>
            <List dense>
              {CHECKS.map(([key, label, ok]) => (
                <ListItem key={key} disableGutters>
                  <ListItemText primary={label} />
                  <Chip size="small" color={ok(report) ? 'success' : 'error'} label={ok(report) ? 'OK' : 'Falla'} />
                </ListItem>
              ))}
            </List>
            <Typography variant="body2" color="text.secondary">
              Tenants comparados: {report.other_tenants_checked}. Tablas revisadas: {report.tables_checked.join(', ')}.
              Se ejecuta como el rol de la app en una transacción de solo lectura y solo devuelve conteos.
            </Typography>
          </Stack>
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={() => setRun((n) => n + 1)} disabled={!report && !error}>
          Ejecutar de nuevo
        </Button>
        <Button onClick={onClose}>Cerrar</Button>
      </DialogActions>
    </Dialog>
  );
}
