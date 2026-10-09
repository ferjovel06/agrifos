# Offline-first y sincronización de campo

Esta entrega pertenece a `feat/offline-first-foundation`, desde `origin/main` en
`8182f9f`. Es una propuesta para revisión, no un despliegue ni una ampliación del
motor agronómico. La auditoría inicial está en [offline-audit.md](offline-audit.md).
La evidencia y las limitaciones están en [offline-validation.md](offline-validation.md).

## Alcance y uso

SQLite nativo es la fuente inmediata de las listas de fincas, parcelas, lecturas,
análisis de laboratorio e instancias fenológicas descargadas. Se puede crear una
lectura OTG y crear/editar un análisis de laboratorio sin internet. Se exige una
parcela ya descargada. Las lecturas son inmutables. No hay borrados offline ni
creación offline de fincas/parcelas; no se inventó un módulo de actividades.

Catálogos, diagnósticos confirmados, planes de fertilización y alertas se pueden
leer si se consultaron previamente con conexión. Esas respuestas auxiliares se
conservan como snapshots: no se recalculan ni se consideran resultados nuevos.
Finanzas, perfil, MFA, registro, recuperación, cambios de configuración y cálculo
de fertilización permanecen online. La actualización de catálogos/resultados
auxiliares requiere invalidación explícita o una futura política versionada;
no son parte del feed incremental inicial.

1. Configura los servicios y `.env` siguiendo el README. Aplica Alembic antes de
   usar la nueva aplicación. El rol de conexión FastAPI debe ser propietario de
   las tablas de sincronización o disponer de privilegios equivalentes; no se
   usa una clave móvil para consultar las tablas privadas vía PostgREST.
2. Inicia sesión online. Espera a la última sincronización y comprueba que la
   finca/parcela requerida aparece. Abre clima y los resultados agronómicos que
   necesitarás antes de salir al campo. La primera descarga necesita conexión.
3. Desconecta internet. Las listas se leen localmente. Captura una lectura o
   guarda una muestra de laboratorio: se confirma su almacenamiento en el
   dispositivo y aparece como pendiente. El guardado espera al commit SQLite.
4. Puedes cerrar y abrir la aplicación. La operación y su UUID sobreviven. Al
   volver a tener acceso real al backend, se sincronizan. Wi-Fi es una señal,
   no una prueba de que FastAPI o internet funcionen.
5. Usa **Sincronizar ahora** y **Ver cambios** para revisar errores/conflictos.
   Se comparan las versiones locales/remotas. Elegir la versión del servidor
   archiva el candidato original; corregir una muestra crea una nueva operación
   con la revisión remota conocida. No se sobrescribe silenciosamente.

## Persistencia y protección

Drift usa SQLite en un isolate, WAL y `synchronous=FULL`, con esquema local v1.
Las tablas son `entities`, `outbox`, `cache` y `checkpoints`. Entidad y outbox se
escriben en una transacción. Los payloads privados, snapshots y versiones de
conflicto usan AES-256-GCM, nonce aleatorio y AAD usuario/entidad/operación.
UUID, tipo, finca, timestamps y estado permanecen como metadatos legibles.

Cada backend/Supabase tiene un namespace propio para su archivo y almacén seguro.
La clave por cuenta, sesión Supabase y PKCE se guardan mediante
`flutter_secure_storage`. La sesión anterior se migra desde SharedPreferences:
primero se guarda de forma segura, después se elimina el original. Android
lleva `allowBackup=false` para evitar restaurar ciphertext sin su clave.
Los tests del protocolo usan un vault de prueba; no certifican Keystore/Keychain.

El primer acceso requiere un perfil verificado por FastAPI. Una concesión local
permite acceso durante **72 horas desde la última verificación exitosa**; errores
de red no amplían ese plazo. Se rechaza el retroceso de reloj respecto de esa
verificación y del último acceso (tolerancia de dos minutos). Al vencer, se
bloquea la interfaz local y se conserva la cola. No se puede conocer de inmediato
una revocación remota estando desconectado. No se ofrece resistencia a un
sistema operativo comprometido ni a la manipulación avanzada del reloj.

Salir elimina la concesión de acceso y la sesión local; conserva datos/operaciones
cifrados por cuenta. Volver a esa cuenta requiere autenticación online. Otra
cuenta no lee ni envía la cola anterior. Los providers se vacían y las respuestas
tardías se invalidan. Una operación ya enviada puede terminar en el servidor de
su propietario; el nuevo usuario no recibe su resultado. La próxima sesión del
propietario recupera el recibo con el mismo UUID.

Plataforma inicial: **Android nativo**. SQLite/cifrado y los tests Flutter se
validaron en Linux, con backend Windows y PostgreSQL Linux. No se certificaron
APK, OTG físico, almacenes seguros nativos, iOS, escritorio ni navegador. La ruta
web permanece online, sin activar SQLite; este checkout heredado no tiene el
scaffold web versionado. Las licencias Android siguen pendientes del usuario.

## Contrato de sincronización

`POST /sync/operations` recibe `operation_id`, `entity_id`, `entity`, `operation`,
`farm_id`, `payload_version=1`, `expected_revision` y `payload`. Solo admite
`readings:create` y `lab_analyses:create/update`. La identidad procede del JWT,
no de un usuario indicado en el payload. Se vuelven a comprobar rol, MFA,
propietario y parcela. Se mantienen ES256, issuer, audiencia y expiración.

Un advisory lock por usuario/operación y un recibo con hash canónico hacen que
los reintentos concurrentes devuelvan la respuesta ya confirmada. Mutación y
recibo se confirman juntos. Reutilizar el UUID con otro payload da 409. La
revisión esperada evita perder ediciones de laboratorio; 409 conserva la versión
remota completa. 422 y 403 no se convierten en reintentos infinitos.

`GET /sync/changes?cursor=...&limit=100` entrega páginas (máximo 200), upserts y
tombstones. El cursor UUID se guarda en el servidor con usuario, frontera fija y
caducidad de 30 días. No se confía en secuencias suministradas por el cliente.
Cada página y checkpoint se aplican atómicamente. Un 410 reinicia el cursor,
conservando entidades y outbox. El diario mantiene los tombstones anteriores.

La migración aditiva `0f11a2b3c4d5` parte de `b2c4d6e8f901`: añade revisiones a
fincas, parcelas, lecturas y análisis, y cuatro tablas privadas. Los triggers
registran también los cambios hechos por endpoints anteriores. Antes de escribir
se serializan las transacciones de dominio con un advisory lock global: la
frontera de descarga no puede saltarse un commit tardío. Es una elección de
corrección con coste de concurrencia; no es una arquitectura para gran volumen.
Una transferencia de propiedad genera tombstone y snapshot para el nuevo dueño;
no se entregan payloads antiguos al dueño revocado. La eliminación de padres
retira hijos confirmados localmente y conserva candidatos pendientes para revisión.

Estados durables: `pending`, `in_progress`, `synced`, `retry_wait`, `conflict`,
`failed_permanent`. Un reinicio recupera `in_progress`. El motor central deduplica
runs, comprueba `/users/me`, envía primero la cola y descarga después el feed.
401 intenta renovación una vez y pausa; 403/404/422 son permanentes; 409 requiere
revisión; 429, timeout y 5xx usan backoff exponencial de 15 segundos con jitter,
base limitada a una hora, `Retry-After` y máximo de ocho intentos. La espera
indicada por el servidor puede superar esa hora. La revisión manual permite
reintentar una operación agotada conservando su UUID.

No hay servicio de sincronización perpetua en segundo plano: funciona al entrar,
volver a foreground, recuperar conectividad, guardar, reintentar o solicitarlo.
No se compactan automáticamente recibos/diario/historial local. Antes de una
escala grande hay que definir retención, snapshots compactados y límites de cola
sin sacrificar dispositivos atrasados. No se deben borrar estos registros para
hacer que un test parezca limpio.

## Clima: tres capas y tres métricas

Panel y Planificación usan siete días y un provider compartido. El cliente guarda
el pronóstico por cuenta, coordenadas truncadas a cuatro decimales, días y versión.
Muestra primero lo guardado, deduplica requests y valida como máximo cada 15
minutos automáticamente, incluyendo el fallo de primera descarga. No consulta
HTTP offline. El timer solo existe con Panel/Planificación visibles y foreground;
la conectividad operativa reactiva la comprobación. Una actualización manual
puede consultar FastAPI, pero no salta la caché del proveedor.

El servidor guarda el producto normalizado elegido y las respuestas HTTP en
PostgreSQL existente. La clave compartida excluye usuario, nombre e ID de finca.
Cada solicitud autoriza primero la finca; su identidad se añade después de leer
el producto público. Advisory locks deduplican workers/reinicios. Se liberan las
lecturas de autorización antes de esperar I/O y se limita la concurrencia de
transacciones anidadas para evitar agotar el pool.

Defaults: fresh 1800 s, histórico a las 21600 s desde descarga, retry 60 s.
MET respeta un `Expires` posterior al TTL, conserva `Last-Modified`, envía
`If-Modified-Since` exacto y reutiliza el cuerpo ante 304. Trunca lat/lon, conserva
User-Agent identificable y respeta 429/`Retry-After`. Fallos y cooldown persisten.
El producto normalizado evita volver a probar un primario fallido mientras el
respaldo siga fresco. Un fallo de ambos mantiene el último pronóstico válido.

`generated_at` identifica generación cuando el proveedor la publica;
`updated_at` la descarga original, `consulted_at` la consulta y `fresh_until` su
frontera. 304 valida sin inventar una descarga nueva. Flutter etiqueta fresh,
stale o histórico y muestra fecha/origen. El histórico no alimenta evaluación de
alertas ni recomendaciones actuales de la tarjeta/calendario.

Métricas separadas: requests Flutter→FastAPI, requests entrantes al servicio de
clima y requests HTTP Open-Meteo/MET. Una reducción en una capa no demuestra por
sí sola reducción en las otras. Los benchmarks usan escenarios controlados;
no son estadísticas de tráfico de producción.

## Dependencias y políticas verificadas

Se reutilizan Provider, modelos, `http`, Supabase y PostgreSQL. Se añaden Drift
2.35.2, secure storage 11.2.0, cryptography 2.9.0 y connectivity 7.3.1. path_provider
2.1.6, uuid 4.6.0 y url_launcher 6.3.2 ya estaban en el lock y ahora son dependencias directas. No se
cambió ninguna versión existente ni el lock Python. Connectivity 7.3.2 no resolvía
el constraint `dbus` de geolocator_linux existente; 7.3.1 conserva ese toolchain.
Dart 3.12.2, Flutter 3.44.9, Java 17, AGP 9.0.1 y Gradle 9.1 se mantienen.

[Drift nativo](https://drift.simonbinder.eu/platforms/vm/) documenta el executor
nativo en isolate. [Secure storage](https://pub.dev/packages/flutter_secure_storage)
requiere Android >=23 y configuración de backup; otros sistemas requieren su
almacén seguro y configuración propia. [Connectivity 7.3.1](https://pub.dev/packages/connectivity_plus/versions/7.3.1)
requiere Java 17/AGP >=8.12.1/Gradle >=8.13 y no garantiza acceso a internet.

[MET Norway](https://api.met.no/doc/TermsOfService) exige identificación, atribución,
caché según Expires y coordenadas con máximo cuatro decimales. La documentación
recomienda proxies/caché y evitar consultas de apps inactivas. Para tráfico alto
se debe acordar uso con MET; no se activó un servicio nuevo.
[Open-Meteo](https://open-meteo.com/en/terms) limita el servicio gratuito a uso no
comercial y a menos de 10 000 requests/día, 5000/hora y 600/minuto. Ambos requieren atribución
CC BY 4.0: la tarjeta meteorológica muestra el proveedor y enlaces a su fuente
y a la licencia. Debe mantenerse esa atribución al publicar.
[La cadencia de modelos Open-Meteo](https://open-meteo.com/en/docs) varía por modelo:
no existe una generación nueva garantizada cada 30 minutos. Puede configurarse
`WEATHER_CACHE_FRESH_SECONDS=3600`; el default conservador sigue siendo 1800 y
nunca adelanta el Expires de MET. Antes de explotación comercial hay que resolver
la modalidad de Open-Meteo y verificar términos/cuotas vigentes.

## Límites operativos

La caché reduce solicitudes equivalentes y aplica cooldown por clave, pero no
implementa un contador global distribuido de cuotas por proveedor. Antes de
tráfico grande deben verificarse los límites agregados de todos los workers y
ubicaciones y, para Open-Meteo comercial, autorizarse una modalidad compatible.
No se contrató ni activó una modalidad de pago.

Los payloads SQLite usan AES-GCM; las claves de consultas privadas usan HMAC con
una clave derivada por cuenta, evitando coordenadas en metadatos de caché. Los
UUID, tipos de entidad, tiempos y estados operativos necesarios para la cola
permanecen como metadatos. No equivale a cifrar todo el archivo SQLite ni protege
frente a un dispositivo comprometido con acceso al almacén seguro. La aceptación
de Android/keystore/OTG sigue pendiente: véase el informe de validación.
