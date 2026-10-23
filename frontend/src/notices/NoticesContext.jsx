import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { api } from '../api/client';

// Avisos de recordatorios dentro de la app (CU-05). Un solo sondeo compartido por la campana y
// la tarjeta de Inicio: al cargar y cada 5 minutos mientras la pestaña está visible.
const POLL_MS = 5 * 60 * 1000;

export const NOTICE_TEXT = {
  self_exam: { title: 'Es momento de tu autoexploración', action: 'Comenzar', to: '/autoexploracion' },
  repeat_analysis: { title: 'Recordatorio: repetir tu análisis de imagen', action: 'Analizar', to: '/analizar' },
};

const NoticesContext = createContext({ notices: [], markRead: async () => {}, refresh: () => {} });

export function NoticesProvider({ children }) {
  const [notices, setNotices] = useState([]);

  const refresh = useCallback(() => {
    api
      .get('/notices', { params: { unread: true, limit: 10 } })
      .then(({ data }) => setNotices(data))
      .catch(() => {
        // Sin avisos si falla: no es crítico y no debe molestar a la paciente
      });
  }, []);

  useEffect(() => {
    refresh();
    const timer = setInterval(() => {
      if (document.visibilityState === 'visible') refresh();
    }, POLL_MS);
    const onVisible = () => document.visibilityState === 'visible' && refresh();
    document.addEventListener('visibilitychange', onVisible);
    return () => {
      clearInterval(timer);
      document.removeEventListener('visibilitychange', onVisible);
    };
  }, [refresh]);

  const markRead = useCallback(async (id) => {
    setNotices((current) => current.filter((n) => n.id !== id));
    try {
      await api.post(`/notices/${id}/read`);
    } catch {
      // Si falla, volverá a aparecer en el siguiente sondeo
    }
  }, []);

  const value = useMemo(() => ({ notices, markRead, refresh }), [notices, markRead, refresh]);
  return <NoticesContext.Provider value={value}>{children}</NoticesContext.Provider>;
}

export function useNotices() {
  return useContext(NoticesContext);
}
