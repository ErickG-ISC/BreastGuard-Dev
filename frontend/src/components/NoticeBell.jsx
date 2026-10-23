import { Badge, IconButton, ListItemText, Menu, MenuItem, Typography } from '@mui/material';
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { NOTICE_TEXT, useNotices } from '../notices/NoticesContext';
import { ReminderIcon } from './icons';

export default function NoticeBell() {
  const { notices, markRead } = useNotices();
  const [anchor, setAnchor] = useState(null);
  const navigate = useNavigate();
  const count = notices.length;

  function open(notice) {
    setAnchor(null);
    markRead(notice.id);
    navigate(NOTICE_TEXT[notice.kind].to);
  }

  return (
    <>
      <IconButton
        aria-label={count ? `Avisos: ${count} sin leer` : 'Avisos'}
        onClick={(event) => setAnchor(event.currentTarget)}
      >
        <Badge badgeContent={count} color="primary">
          <ReminderIcon />
        </Badge>
      </IconButton>
      <Menu anchorEl={anchor} open={Boolean(anchor)} onClose={() => setAnchor(null)}>
        {count === 0 && (
          <MenuItem disabled>
            <Typography variant="body2">No tienes avisos pendientes</Typography>
          </MenuItem>
        )}
        {notices.map((notice) => (
          <MenuItem key={notice.id} onClick={() => open(notice)}>
            <ListItemText
              primary={NOTICE_TEXT[notice.kind]?.title ?? 'Recordatorio'}
              secondary={new Date(notice.due_at).toLocaleString('es-MX', { dateStyle: 'medium', timeStyle: 'short' })}
            />
          </MenuItem>
        ))}
      </Menu>
    </>
  );
}
