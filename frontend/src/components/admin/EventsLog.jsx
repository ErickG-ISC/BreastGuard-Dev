import {
  Alert,
  Button,
  Card,
  CardContent,
  CircularProgress,
  FormControl,
  InputLabel,
  MenuItem,
  Select,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TextField,
  Typography,
  useMediaQuery,
} from '@mui/material';
import { useEffect, useState } from 'react';
import { api, errorMessage } from '../../api/client';
import { ACTION_LABELS, PLAN_LABELS, ROLE_LABELS, formatDateTime } from '../../pages/admin/adminLabels';

const PAGE = 25;

function describe(event) {
  const parts = [];
  if (event.details?.fields) parts.push(`campos: ${event.details.fields.join(', ')}`);
  if (event.details?.role) parts.push(`rol: ${ROLE_LABELS[event.details.role] ?? event.details.role}`);
  if (event.details?.plan) parts.push(`plan: ${PLAN_LABELS[event.details.plan] ?? event.details.plan}`);
  return parts.join(' · ');
}

// Bitácora de plataforma (ADR 0008). `url`: /admin/events (todo) o /institution/events (su
// tenant; el servidor impone el alcance). `tenants`: mapa id -> nombre para mostrar.
export default function EventsLog({ url, tenants = null, fixedTenantId = null }) {
  const desktop = useMediaQuery((theme) => theme.breakpoints.up('md'));
  const [filters, setFilters] = useState({ action: '', from: '', to: '' });
  const [offset, setOffset] = useState(0);
  const [page, setPage] = useState(null);
  const [error, setError] = useState('');

  useEffect(() => {
    const params = { limit: PAGE, offset };
    if (filters.action) params.action = filters.action;
    if (filters.from) params.from = `${filters.from}T00:00:00`;
    if (filters.to) params.to = `${filters.to}T23:59:59`;
    if (fixedTenantId) params.tenant_id = fixedTenantId;
    api
      .get(url, { params })
      .then(({ data }) => {
        setPage(data);
        setError('');
      })
      .catch((err) => setError(errorMessage(err, 'No se pudo cargar la bitácora.')));
  }, [url, filters, offset, fixedTenantId]);

  const set = (field) => (event) => {
    setOffset(0);
    setFilters((current) => ({ ...current, [field]: event.target.value }));
  };
  const tenantName = (id) => (tenants && id ? (tenants[id] ?? 'Institución purgada') : null);
  const items = page?.items ?? [];

  return (
    <Stack spacing={2}>
      <Card>
        <CardContent>
          <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2}>
            <FormControl size="small" sx={{ minWidth: 220 }}>
              <InputLabel id="filtro-accion">Acción</InputLabel>
              <Select labelId="filtro-accion" label="Acción" value={filters.action} onChange={set('action')}>
                <MenuItem value="">Todas</MenuItem>
                {Object.entries(ACTION_LABELS).map(([code, label]) => (
                  <MenuItem key={code} value={code}>
                    {label}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
            <TextField
              size="small"
              label="Desde"
              type="date"
              value={filters.from}
              onChange={set('from')}
              slotProps={{ inputLabel: { shrink: true } }}
            />
            <TextField
              size="small"
              label="Hasta"
              type="date"
              value={filters.to}
              onChange={set('to')}
              slotProps={{ inputLabel: { shrink: true } }}
            />
          </Stack>
        </CardContent>
      </Card>
      {error && <Alert severity="error">{error}</Alert>}
      {!page && !error && <CircularProgress sx={{ alignSelf: 'center' }} />}
      {page && items.length === 0 && (
        <Typography variant="body2" color="text.secondary">
          Sin registros con estos filtros.
        </Typography>
      )}
      {page && items.length > 0 && desktop && (
        <Card>
          <Table size="small" aria-label="Bitácora">
            <TableHead>
              <TableRow>
                <TableCell>Fecha y hora</TableCell>
                <TableCell>Acción</TableCell>
                {tenants && <TableCell>Institución</TableCell>}
                <TableCell>Quién</TableCell>
                <TableCell>Detalle</TableCell>
                <TableCell>IP</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {items.map((event) => (
                <TableRow key={event.id}>
                  <TableCell>{formatDateTime(event.occurred_at)}</TableCell>
                  <TableCell>{ACTION_LABELS[event.action] ?? event.action}</TableCell>
                  {tenants && <TableCell>{tenantName(event.tenant_id) ?? '—'}</TableCell>}
                  <TableCell>{ROLE_LABELS[event.actor_role] ?? event.actor_role}</TableCell>
                  <TableCell>{describe(event) || '—'}</TableCell>
                  <TableCell>{event.ip ?? '—'}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Card>
      )}
      {page &&
        !desktop &&
        items.map((event) => (
          <Card key={event.id}>
            <CardContent>
              <Typography variant="subtitle2">{ACTION_LABELS[event.action] ?? event.action}</Typography>
              <Typography variant="body2" color="text.secondary">
                {formatDateTime(event.occurred_at)} · {ROLE_LABELS[event.actor_role] ?? event.actor_role}
                {tenants && event.tenant_id ? ` · ${tenantName(event.tenant_id)}` : ''}
              </Typography>
              {describe(event) && <Typography variant="body2">{describe(event)}</Typography>}
            </CardContent>
          </Card>
        ))}
      {page && page.total > PAGE && (
        <Stack direction="row" sx={{ justifyContent: 'space-between', alignItems: 'center' }}>
          <Typography variant="body2" color="text.secondary">
            Mostrando {offset + 1}–{Math.min(offset + PAGE, page.total)} de {page.total}
          </Typography>
          <Stack direction="row" spacing={1}>
            <Button disabled={offset === 0} onClick={() => setOffset(offset - PAGE)}>
              Anterior
            </Button>
            <Button disabled={offset + PAGE >= page.total} onClick={() => setOffset(offset + PAGE)}>
              Siguiente
            </Button>
          </Stack>
        </Stack>
      )}
    </Stack>
  );
}
