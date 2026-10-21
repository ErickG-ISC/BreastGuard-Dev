import axios from 'axios';

const TOKEN_KEY = 'bg_token';

// El JWT vive en sessionStorage (se borra al cerrar la pestaña). Expuesto a XSS: aceptado
// para el prototipo con expiración de 30 minutos (ver docs/adr/0003).
export const tokenStore = {
  get() {
    try {
      return sessionStorage.getItem(TOKEN_KEY);
    } catch {
      return null;
    }
  },
  set(token) {
    try {
      sessionStorage.setItem(TOKEN_KEY, token);
    } catch {
      // Sin almacenamiento disponible: la sesión dura solo mientras la página esté abierta
    }
  },
  clear() {
    try {
      sessionStorage.removeItem(TOKEN_KEY);
    } catch {
      // nada que limpiar
    }
  },
};

export const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL ?? 'http://localhost:8000/api/v1',
});

api.interceptors.request.use((config) => {
  const token = tokenStore.get();
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401 && tokenStore.get()) {
      tokenStore.clear();
      window.dispatchEvent(new Event('bg:logout'));
    }
    return Promise.reject(error);
  },
);

export function errorMessage(error, fallback = 'Ocurrió un error. Intenta de nuevo.') {
  const detail = error?.response?.data?.detail;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail) && detail[0]?.msg) return detail[0].msg;
  if (error?.response?.status === 429) return 'Demasiados intentos. Espera un momento.';
  return fallback;
}
