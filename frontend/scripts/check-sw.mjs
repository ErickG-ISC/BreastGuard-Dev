// Verifica, después de `npm run build`, que el service worker de la PWA solo guarde archivos
// estáticos de la app: nunca respuestas de la API ni imágenes médicas. Lo corre el CI.
import { readFileSync } from 'node:fs';

const sw = readFileSync(new URL('../dist/sw.js', import.meta.url), 'utf8');
const errors = [];

// Ninguna estrategia de caché en tiempo de ejecución (es lo que guardaría respuestas de la API)
for (const strategy of ['CacheFirst', 'NetworkFirst', 'StaleWhileRevalidate', 'CacheOnly', 'ExpirationPlugin']) {
  if (sw.includes(strategy)) errors.push(`sw.js usa la estrategia de caché ${strategy}`);
}

// Ni manejadores de fetch propios ni acceso directo a la Cache API
for (const pattern of [/addEventListener\(\s*["']fetch["']/, /caches\.open\(/, /setCatchHandler|setDefaultHandler/]) {
  if (pattern.test(sw)) errors.push(`sw.js contiene ${pattern}`);
}

// La configuración fuente también debe declarar que no hay caché en tiempo de ejecución
const config = readFileSync(new URL('../vite.config.js', import.meta.url), 'utf8');
if (!/runtimeCaching:\s*\[\s*\]/.test(config)) errors.push('vite.config.js debe tener runtimeCaching: []');

// La única ruta registrada es la navegación de la SPA, con /api/ excluido
const routes = sw.match(/registerRoute\(/g) ?? [];
if (routes.length !== 1 || !sw.includes('NavigationRoute')) {
  errors.push(`sw.js registra ${routes.length} rutas; se esperaba solo la NavigationRoute`);
}
if (!sw.includes('denylist:[/^\\/api\\//]')) errors.push('La NavigationRoute no excluye /api/');

// El precache solo lleva el cascarón de la app: HTML, JS, CSS, íconos y el manifiesto
const allowed = [
  /^index\.html$/,
  /^registerSW\.js$/,
  /^manifest\.webmanifest$/,
  /^(favicon|icons)\.svg$/,
  /^pwa-\d+\.png$/,
  /^assets\/[\w.-]+\.(js|css|svg|woff2)$/,
];
const urls = [...sw.matchAll(/url:"([^"]+)"/g)].map((m) => m[1]);
if (urls.length === 0) errors.push('No se encontró la lista de precache en sw.js');
for (const url of urls) {
  if (!allowed.some((re) => re.test(url))) errors.push(`Archivo inesperado en el precache: ${url}`);
}

if (errors.length) {
  console.error(`check-sw: ${errors.length} problema(s)\n- ${errors.join('\n- ')}`);
  process.exit(1);
}
console.log(`check-sw: OK (${urls.length} archivos estáticos en precache, sin caché de la API)`);
