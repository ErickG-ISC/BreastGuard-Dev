import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { api, tokenStore } from '../api/client';

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(() => Boolean(tokenStore.get()));

  const loadMe = useCallback(async () => {
    try {
      const { data } = await api.get('/auth/me');
      setUser(data);
    } catch {
      tokenStore.clear();
      setUser(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (tokenStore.get()) loadMe();
    const onLogout = () => setUser(null);
    window.addEventListener('bg:logout', onLogout);
    return () => window.removeEventListener('bg:logout', onLogout);
  }, [loadMe]);

  const login = useCallback(
    async (email, password) => {
      // El endpoint es OAuth2: formulario x-www-form-urlencoded con username y password
      const form = new URLSearchParams({ username: email, password });
      const { data } = await api.post('/auth/token', form);
      tokenStore.set(data.access_token);
      setLoading(true);
      await loadMe();
    },
    [loadMe],
  );

  const logout = useCallback(() => {
    tokenStore.clear();
    setUser(null);
  }, []);

  const value = useMemo(() => ({ user, loading, login, logout }), [user, loading, login, logout]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  return useContext(AuthContext);
}
