import { api } from './client';

// Descarga de un archivo protegido (CU-10): con el token en el header, nunca en la URL. El nombre
// del archivo lo da el servidor (sin datos personales).
export async function downloadFile(path, fallbackName = 'breastguard-reporte') {
  const response = await api.get(path, { responseType: 'blob' });
  const disposition = response.headers['content-disposition'] ?? '';
  const match = /filename="([^"]+)"/.exec(disposition);
  const url = URL.createObjectURL(response.data);
  const link = document.createElement('a');
  link.href = url;
  link.download = match ? match[1] : fallbackName;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

// Con responseType 'blob' el error del servidor también llega como Blob: se lee su `detail`.
export async function downloadError(err, fallback) {
  const data = err?.response?.data;
  if (data instanceof Blob) {
    try {
      const body = JSON.parse(await data.text());
      if (typeof body?.detail === 'string') return body.detail;
    } catch {
      // no era JSON
    }
  }
  return fallback;
}
