# ADR 0010: Paquete compartido cifrado (CU-07)

- Estado: aceptado (crear, listar, revocar, caducar e importar)
- Fecha: 2026-11-04
- Casos de uso: CU-07 (compartir con la médica) y CU-08 (importar)

## Contexto

La paciente B2C y su médica viven en tenants distintos. Compartir no puede abrir ninguna política
entre tenants (ADR 0002): la paciente genera una **copia** que la médica importa en su propio
tenant. Además, el servidor no debe poder leer lo compartido ni guardar el código que lo abre.

## Decisiones

1. **Código como llave.**
   - 16 bytes aleatorios (128 bits) en base32 Crockford: 26 caracteres en grupos (5-5-5-5-6).
     Al leerlo se ignoran guiones, espacios y mayúsculas, y se aceptan O/I/L por 0/1.
   - Con HKDF-SHA256 se derivan dos valores independientes: la llave AES-256-GCM y un
     identificador de búsqueda.
   - El servidor guarda solo `HMAC-SHA256(SECRET_KEY, identificador)` en
     `control.share_packages.key_hash`, con índice único.
   - El código no se guarda, no se registra en logs y se devuelve **una sola vez**
     (`Cache-Control: no-store`).
   - El enlace es `PUBLIC_APP_URL/importar#c=CÓDIGO`. Como va en el fragmento, nunca llega al
     servidor, a los logs ni al Referer. El QR (`qrcode`, en el navegador) codifica ese enlace.
2. **Contenido cifrado en Storage privado** bajo `transfer/{uuid}/` (`transfer` es un slug
   reservado).
   - Cada imagen y cada heatmap va como un objeto `{uuid}.bin`, y el contenido JSON como
     `payload.bin`.
   - Cada objeto lleva un nonce aleatorio y, como datos asociados (AAD), el id del paquete y su
     nombre: no se puede mover un archivo a otro paquete ni renombrarlo.
3. **Solo objetos propios.**
   - El paquete se arma con la sesión `TenantDb` de la paciente, bajo RLS y con el filtro de
     pertenencia (`patient_id` de su ficha).
   - Las rutas de Storage salen de sus filas, nunca del cliente, y deben empezar por `{su_slug}/`.
   - Un análisis ajeno o inexistente da el mismo 422.
   - Límites: como máximo 10 análisis, 25 MB, 5 paquetes activos por paciente y 5 peticiones por
     minuto.
4. **Qué se comparte lo elige ella:**
   - análisis;
   - diario y autoexploraciones de 90 días;
   - último cuestionario;
   - opcionalmente sus notas escritas;
   - opcionalmente nombre y edad. La edad es la del cuestionario con su fecha, nunca la fecha de
     nacimiento.

   En `share_packages.sections` solo quedan booleanos.
5. **Control sin datos clínicos** (migración 0015):
   - `share_packages`: estado, caducidad (24 h, 3 o 7 días; un CHECK impone el máximo de 7 días),
     destinataria opcional, consentimiento (versión y sha256), prefijo, intentos fallidos y quién
     importó;
   - `share_events`: lo que ve la paciente (creado, revocado, caducado, importado, reasignado),
     con nombres de institución y médica, nunca contenido;
   - `inbox_notices`: avisos internos con tipo e id.
6. **Defensa en la base.** `control` no tiene RLS y `app_user` también es el rol de las sesiones
   clínicas, así que el trigger `control.enforce_share_writes` asegura:
   - con contexto de paciente solo se crean paquetes **a su nombre** y empiezan activos;
   - en su contexto, la paciente solo puede revocar los suyos;
   - ninguna sesión con contexto de doctora o administración toca paquetes;
   - la importación y la limpieza usan sesiones de control sin contexto.
7. **Destinataria opcional y sin revelar cuentas.**
   - Si el correo es de una doctora activa de una institución activa, se guarda su id: recibe un
     aviso interno y un correo discreto, sin nombre de la paciente ni tema.
   - En cualquier otro caso, la respuesta es idéntica.
8. **Revocar y caducar.**
   - La paciente revoca un paquete activo, y su contenido se borra de inmediato.
   - `POST /internal/shares/cleanup` usa el mismo secreto del despachador y la sesión de control.
     Caduca lo vencido y borra el contenido de lo revocado, caducado o importado; si Storage
     falla, lo reintenta en la siguiente corrida.
   - Lo llama `reminders.yml` cada 15 minutos.
9. **Consentimiento del paquete** (`content/share_consent_v1.md`, BORRADOR):
   - nombra como custodia a la **institución** de la médica que importa, no a "la Dra. X";
   - avisa que la institución puede asignar el caso a otra médica (traspaso, ADR 0009);
   - avisa que la copia importada no se retira desde BreastGuard.

   Así el texto coincide con el comportamiento real. Cada cambio de médica se verá en
   "Mis paquetes" como un evento `reasignado`, que llega con la importación.

10. **Revisión de aislamiento** (sin hallazgos críticos; los medios se corrigieron en 0015):
    - `fk_share_packages_recipient` usa `ON DELETE SET NULL`: un paquete dirigido a una médica
      no bloquea la purga de su institución.
    - Triggers en `share_events` e `inbox_notices`. Con contexto de paciente:
      - solo hay eventos `creado` o `revocado`, sin nombres;
      - solo sobre sus propios paquetes;
      - solo avisa a la destinataria resuelta de su paquete;
      - solo la dueña del aviso lo marca como leído.
    - `object_prefix` es, por CHECK, el del propio paquete (`transfer/` + id sin guiones), y es
      único. La paciente solo marca el contenido como borrado en un paquete revocado.
    - Ningún tenant puede llamarse `transfer`: hay un CHECK en `control.tenants`, y
      `remove_prefix` rechaza `transfer/` como prefijo de tenant.
    - El correo a la destinataria sale en segundo plano, para que su latencia no revele si el
      correo tiene cuenta.
    - El HMAC lleva un prefijo de dominio, porque `SECRET_KEY` también firma los JWT.

11. **Importación como copia** (CU-08, `services/share_import.py`,
    `POST /doctor/shares/import`, solo doctora, 10/min):
    1. **Reclamo atómico en control** (sesión sin contexto): un solo UPDATE pasa el paquete a
       `importando` si el código es vigente, la destinataria es ella o no hay destinataria, y el
       paquete está activo (o es un reclamo suyo de hace más de 10 minutos). Solo una petición
       gana. Cualquier otro caso (segundo uso, caducado, revocado, código incorrecto u otra
       destinataria) da el mismo 404.
    2. **Descifrado en memoria:** la etiqueta de AES-GCM prueba la llave.
    3. **Copia en la sesión `TenantDb` de la doctora**, bajo RLS de su tenant:
       - ficha `importado` con ella como responsable y `source_package_id`;
       - imágenes y heatmaps a `{su_slug}/...` con rutas nuevas;
       - análisis, autoexploraciones, diario (con sus enlaces) y cuestionario, con ids nuevos;
       - `share.import` en su auditoría.
    4. **Confirmación en control:**
       - estado `importado`;
       - evento `importado` con los nombres de su institución y de ella;
       - su aviso queda leído;
       - se borra `transfer/`.
    - **Si algo falla:** rollback, borrado de lo subido y liberación del reclamo (se puede
      reintentar). Si el proceso muere entre copiar y confirmar, el reintento encuentra la ficha
      por el índice único y solo confirma, sin duplicar.
    - **Intentos fallidos:** 5 por cuenta en 15 minutos (en memoria, como el resto del límite de
      peticiones). Un código válido intentado por otra cuenta suma al paquete; a los 5, se revoca.
12. **`reasignado`** (0016): al aceptar un traspaso de fichas importadas, la doctora que acepta
    escribe el evento con su contexto. El trigger lo admite solo si:
    - el paquete se importó en su tenant;
    - una ficha de ese paquete la tiene como responsable;
    - los nombres son los suyos y los de su institución.

    Crear un traspaso además avisa por correo a la médica de origen y a las demás administradoras
    (riesgo de una segunda cuenta de la misma persona, ADR 0009).
    - **Contenido no confiable** (revisión de aislamiento): el contenido descifrado se valida
      con `schemas/share_payload.py` antes de copiar nada. El esquema impone:
      - tipos cerrados y sin campos extra;
      - nombres de objeto `^[0-9a-f]{32}\.bin$`, nunca rutas;
      - como máximo 10 análisis y nunca más que `analyses_count`;
      - límites de longitud.

      Cualquier error libera el reclamo y borra lo subido (502, nunca 500).
    - **Confirmación:** `_confirm` solo confirma si el reclamo sigue siendo de quien importa.
      La limpieza no caduca un reclamo de menos de 10 minutos.
    - **Destinataria purgada:** si se purga su institución, `recipient_user_id` queda nulo y el
      código sirve a cualquier doctora que lo tenga, hasta que caduque.
13. **Frontend:**
    - `/importar` es pública: guarda el código del fragmento en `sessionStorage`, lo borra del
      historial y pide iniciar sesión;
    - `/medico` lleva a la médica a `/medico/importar` y muestra el aviso "tienes un paquete".
   - el código pendiente se borra al cerrar sesión y si quien abre el enlace no es doctora.

## Consecuencias

- Rotar `SECRET_KEY` invalida los paquetes activos (duran como máximo 7 días) y las sesiones.
- La caducidad la registra la limpieza en `share_events`, no en el `audit_log` del tenant de la
  paciente: la limpieza no tiene contexto clínico. La creación y la revocación sí van en su
  auditoría.
- Si el proceso muere entre subir y confirmar, quedan objetos cifrados sin fila bajo
  `transfer/`. No tienen llave; una pasada que borre carpetas huérfanas queda pendiente.
- El tope de 5 paquetes activos no es atómico ante peticiones simultáneas; lo acota el límite de
  5 por minuto.

- Con acceso a la base, sin el código, el contenido no se puede descifrar. Sin `SECRET_KEY`
  tampoco se pueden probar códigos contra el hash.
- El código es un secreto al portador: quien lo tenga y sea doctora puede importarlo si no hay
  destinataria. Lo mitigan la caducidad corta, el uso único y la revocación.
- La purga de un tenant borra sus paquetes y el contenido de `transfer/` de cada uno.
- `cryptography` queda fijada explícitamente (ya venía con `python-jose`).
- La paciente ve `importado` y `reasignado` en "Mis paquetes"; la campana de la paciente
  todavía no muestra estos avisos.
