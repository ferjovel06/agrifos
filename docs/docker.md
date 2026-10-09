# Desarrollo local con Docker

Esta infraestructura prepara el backend, Supabase Auth local y herramientas Flutter.
**La validación todavía es parcial y no hay aprobación para integrar en main.**
El adaptador resuelve la publicación loopback en Docker Desktop 4.55.0. El driver real
de Auth/MFA/persistencia y Alembic pasa, y la base Trixie conserva Python y el lockfile.
Trivy sigue en FAIL por ocho CVEs Debian (44 HIGH); Android permanece pendiente y
el CI Docker global falla por ese gate, aunque las pruebas Linux funcionales pasan.
Consulta [la resolución del conflicto y su validación](docker-pr76-merge.md),
[la entrega Docker inicial](docker-closeout.md),
[los riesgos pendientes](docker-security-risk-register.md) y
[la validación inicial](docker-validation.md). Conserva el preflight habilitado.

## Requisitos y alcance

- Hosts objetivo: Windows x64 con Git Bash y Docker Desktop usando contenedores Linux/WSL2,
  y Linux x86_64 con Docker Engine. Backend, Supabase y Flutter tools se comprobaron en Windows.
  El adaptador tiene pruebas ejecutadas en Windows y Linux; el flujo completo en un host
  Linux también pasó en GitHub Actions Ubuntu 24.04 amd64. El gate de seguridad
  continúa fallando; esos resultados no aprueban el entorno completo. ARM, macOS e iOS no están validados.
- Git, Bash y Docker Compose v2. El equipo de desarrollo tiene cliente Docker 29.1.3,
  Compose 2.40.3 y WSL 2.6.3. La CLI Supabase autónoma se descarga en `.tools/`;
  no necesita Node/npm ni instalación global. Git Bash debe incluir curl, unzip,
  sha256sum, timeout, awk y las herramientas Unix habituales.
- El daemon debe responder a `docker version` con secciones **Client y Server**.
  Tener `docker.exe` o `docker compose` no acredita ese requisito.
- La primera preparación necesita Internet y espacio para imágenes, Flutter y Android SDK/NDK.
  Intervienen Docker Hub/GHCR, GitHub Releases, PyPI, pub.dev, Google Storage/SDK/Maven,
  Maven Central y las distribuciones de Gradle. No se promete uso offline inicial
  ni artefactos idénticos bit a bit.
- GUI, hot reload, emulador, ADB, ubicación, USB/OTG y sensores requieren herramientas
  y hardware del host. Los contenedores generan herramientas/APK; no ejecutan un teléfono.
  El APK solo es debug. Las claves y la firma release existentes quedan fuera del flujo.

No instales/reconfigures Docker Desktop, WSL, servicios o permisos automáticamente.
En Windows, abre tu Docker Desktop configurado y espera su estado operativo. Los scripts
fallan cuando el daemon no responde. Si hay un conflicto de recursos, preserva los datos
y usa otro checkout/proyecto de pruebas; no ejecutes prune ni limpiezas globales.

## Versiones controladas

| Componente | Pin |
|---|---|
| Backend | Python 3.13.16 slim-trixie; uv 0.12.2, ambos por digest OCI |
| Dependencias Python | `backend/pyproject.toml` + `backend/uv.lock`; `uv sync --locked` |
| Correcciones dirigidas Python | PyJWT 2.14.0 y urllib3 2.8.0; los demás paquetes conservan su versión |
| Supabase CLI | 2.120.0; archivos autónomos y SHA256 de release fijados |
| Adaptador loopback | Go 1.27.2 por digest, compilado en Docker; ejecutables locales Windows/Linux, sin instalar Go en el host |
| PostgreSQL local | Versión mayor 17; imágenes de servicios elegidas por la CLI fijada |
| Flutter / Dart | 3.44.9 stable / 3.12.2; archivo oficial con SHA256 |
| Java | Temurin 17.0.20.1+1, base Ubuntu Noble por digest |
| Android | CLI 22.0; Platform Tools 37.0.1; SDK 36; Build Tools 36.0.0; NDK 28.2.13676358 |
| Gradle / AGP / Kotlin | 9.1.0 / 9.0.1 / 2.3.20; conserva la configuración existente |

Los pins exactos están en los Dockerfiles y el instalador. El SDK Android conserva las
versiones derivadas del Flutter elegido. Pub usa `pubspec.lock` y restauración
`--enforce-lockfile`; cada tarea comprueba que sus manifiestos/configuración no cambiaron.
APT instala un conjunto pequeño de paquetes de Ubuntu; esos paquetes no están fijados
individualmente. Las imágenes de servicios Supabase usan los tags de la CLI; registrar sus
digests efectivos de los cuatro servicios usados quedaron registrados en la evidencia
de esta fase; los tags vendor siguen siendo externos y no se presume inmutabilidad futura.

## Incorporación breve

Los comandos siguientes son **comandos de terminal**, desde la raíz del repositorio.
En Windows, ejecútalos en **Git Bash**, no en el `bash.exe` de WSL por accidente.

```bash
git clone https://github.com/ferjovel06/agrifos.git
cd agrifos
# Antes de integrar el PR, usar su rama publicada:
git switch --track origin/chore/docker-environment
docker version
docker compose version
bash scripts/docker-dev.sh prepare
bash scripts/install-supabase.sh
bash scripts/docker-dev.sh check
bash scripts/docker-dev.sh build
bash scripts/supabase-local.sh start
bash scripts/docker-dev.sh configure
bash scripts/docker-dev.sh up
bash scripts/docker-dev.sh health
```

La preparación no sobrescribe archivos env existentes. El instalador preserva una
instalación local existente y rechaza versiones distintas. La CLI incluye dos ejecutables:
conserva `supabase` y `supabase-go` juntos. Los archivos dotenv reales en raíz o en
`supabase/` se rechazan para evitar que la CLI cargue overrides inesperados;
`backend/.env` y `app_flutter/.env` del flujo nativo no se montan ni se leen para Docker.

`configure` obtiene el estado local por stdin, sin mostrar tokens, y crea:

- `.docker/local/backend.env`: conexión interna PostgreSQL, URL pública Supabase y JWKS interno.
- `.docker/local/client.env`: solo URL Supabase, clave pública publishable/anon y URL API,
  inicialmente para el emulador Android.

Si ya existen, se preservan. Para cambiar una configuración, edita el archivo local
deliberadamente o consérvalo con otro nombre antes de regenerarlo. No pegues secretos
en el chat ni ejecutes `docker compose config` sin `--quiet` con configuración real.

## Arquitectura, URLs y autenticación

La CLI inicia PostgreSQL, GoTrue/Auth, gateway y correo local; Studio es opcional.
Compose inicia `migrate` y después `api`, y ofrece tareas unitarias/Flutter independientes.
Ambos comparten **una red necesaria**, `agrifos-local`, con publicación loopback.
Los scripts verifican propiedad y bindings; rechazan recursos incompatibles preexistentes.
`supabase-local.sh` construye/verifica automáticamente un adaptador nativo en `.tools/`.
Solo el proceso hijo de Supabase CLI recibe su directorio al inicio de PATH. El adaptador
delegará al Docker nativo capturado por ruta absoluta y convierte cada publicación del
CLI en `127.0.0.1:puerto_host:puerto_contenedor`. Rechaza IPs distintas, publish-all,
host networking, flags de creación desconocidos y creaciones/arranques de otro proyecto/workdir.
Comprueba los bindings solicitados antes de `start` y los efectivos después; si el daemon
devuelve una publicación insegura, intenta detener únicamente ese contenedor propio.
Las tareas temporales de inicialización del CLI se admiten solo en la red/proyecto propios,
sin puertos ni binds cuando falta su etiqueta workdir, que el adaptador añade.
El preflight requiere el runtime backend construido y comprueba la publicación con un
contenedor temporal sin listener ni credenciales. Elimina únicamente esa sonda identificada;
si el daemon publica fuera de loopback, no inicia Supabase. Las tareas Flutter reutilizan
el bridge estándar Docker para descargas y no requieren crear la red de Supabase.
`start` prepara la red identificada y ejecuta esa comprobación automáticamente;
`bash scripts/supabase-local.sh preflight` permite repetirla sobre una red ya preparada.

| Consumidor | API Agrifos | Supabase Auth/API | PostgreSQL |
|---|---|---|---|
| Host/navegador | `http://127.0.0.1:8000` | `http://127.0.0.1:54321` | `127.0.0.1:54322` |
| Contenedores | `http://api:8000` | `http://supabase_kong_agrifos:8000` | `supabase_db_agrifos:5432` |
| Emulador Android | `http://10.0.2.2:8000` | `http://10.0.2.2:54321` | No se expone al cliente |
| Teléfono con ADB reverse | `http://127.0.0.1:8000` | `http://127.0.0.1:54321` | No se expone al cliente |

Correo de pruebas: `http://127.0.0.1:54324`. Con `start --studio`, Studio usa
`http://127.0.0.1:54323`; no inicia servicios de almacenamiento/realtime que Agrifos no usa.
La CLI sí descarga y ejecuta helpers de Storage/Realtime al inicializar sus esquemas;
son dependencias de bootstrap, aunque sus servicios permanentes se excluyen.
`localhost` dentro de un contenedor es ese contenedor, y **54321 no es el puerto DB**.

El issuer local es exactamente `http://127.0.0.1:54321/auth/v1`. `SUPABASE_URL`
conserva esa URL pública base para derivarlo. Solo se añadió `SUPABASE_JWKS_URL`
para obtener las claves por DNS interno. Un `SUPABASE_JWT_ISSUER` separado no fue necesario.
Se conservan ES256, audiencia `authenticated`, firma, expiración e issuer. Los defaults
del despliegue existente siguen derivándose de `SUPABASE_URL`; `render.yaml` no cambió.
PyJWT 2.14.0 rechaza redirecciones JWKS: una respuesta 301/302/303/307/308 produce el
503 existente y no se consulta el destino. Las regresiones HTTP comprueban este caso.
Su cooldown predeterminado de 30 segundos puede retrasar una clave con kid nuevo tras
una descarga reciente; la rotación posterior está probada y no se desactiva esa protección.

Cada proyecto genera su clave ES256 en `supabase/.local/signing-keys.json`, ignorada y
sin sobrescribirla. Supabase crea `auth.users` y `auth.mfa_factors`; Alembic reutiliza sus
migraciones históricas y el trigger de perfiles. TOTP se habilita en el entorno local.
No se crean tablas Auth falsas. El correo conserva confirmación y los deep links existentes.

Un `.env` que Compose usa para interpolación no se inyecta automáticamente en la aplicación.
Aquí `AGRIFOS_*` controla Compose; `env_file` inyecta la configuración concreta del backend.
Las tareas unitarias usan únicamente los valores ficticios del script nativo; nunca son
configuración válida para arrancar Auth real.

## Backend, migraciones y persistencia

```bash
bash scripts/docker-dev.sh test
bash scripts/docker-dev.sh migrate
bash scripts/docker-dev.sh logs
bash scripts/docker-dev.sh health
bash scripts/docker-dev.sh stop
bash scripts/supabase-local.sh stop
# Reiniciar sin borrar datos:
bash scripts/supabase-local.sh start
bash scripts/docker-dev.sh up
```

`migrate` espera hasta 180 segundos consultando la BD y las tablas Auth reales; ejecuta
`alembic upgrade head` con fallo visible. No hay migración en cada worker.
El healthcheck API comprueba `/health/db`; `/health` solo acredita vida del proceso,
y `SELECT 1` tampoco acredita por sí solo el esquema: la migración debe terminar primero.

API y migraciones usan UID 10001, sin capacidades y con `no-new-privileges` en Compose.
El runtime no incluye uv/reload ni instalación al arrancar:

```bash
bash scripts/docker-dev.sh stop
docker compose --profile runtime up -d --wait --wait-timeout 180 api-runtime
docker compose exec -T api-runtime python --version
docker compose exec -T api-runtime alembic current
docker compose stop api-runtime
```

Desarrollo monta `app/` y `alembic/` en solo lectura para el contenedor; editar desde el
host dispara recarga de `app/`. Las dependencias permanecen en `/opt/venv`, fuera del
montaje. Si cambias manifiestos/locks, reconstruye deliberadamente la imagen.

Los volúmenes DB sobreviven a `stop` y a recrear contenedores. Los scripts no ejecutan
`down -v`, `db reset`, `prune`, `stamp` ni borran volúmenes preexistentes.

## Integración real y diagnóstico del esquema

```bash
bash scripts/test-docker-integration.sh
```

Este comando crea un proyecto **nuevo** `agrifos-it-<id>`, otra instancia aislada de la misma
topología y puertos 54331–54334/API 8010. Rechaza destinos remotos y operaciones sobre el
proyecto de desarrollo. Prueba health, migración/head, creación administrativa de usuario
sintético confirmado, trigger antes del primer acceso API, login real, JWT ES256, rechazo
de contraseña/firma inválidas, MFA TOTP, repetición de migraciones y reinicio preservando datos.
También rechaza JWT firmados con la clave local pero audience/issuer/exp incorrectos,
HS256 y tokens malformados; prueba Alembic antes/después del reinicio y la detección
de drift real de columnas/índices/FKs mediante metadata temporal y transacción de solo lectura.
En Windows corrobora los cuatro listeners con Get-NetTCPConnection.
No prueba el recorrido completo de enlaces de confirmación ni hardware.

El usuario sintético se elimina solo tras éxito dentro de ese proyecto nuevo. Ante fallos,
se detienen los recursos propios y se preservan volúmenes/evidencia en
`.docker/integration/<id>/`. Esa evidencia puede contener credenciales locales de prueba;
no la publiques. El proceso no muestra tokens ni cuerpos de error Auth.

Para inspeccionar un proyecto retenido, usa la identidad que imprimió el script:

```bash
export AGRIFOS_ENV_DIR=.docker/integration/agrifos-it-XXXXXXXX
export AGRIFOS_SUPABASE_WORKDIR="$PWD/$AGRIFOS_ENV_DIR"
export AGRIFOS_NETWORK=agrifos-it-XXXXXXXX
export AGRIFOS_API_PORT=8010
bash scripts/supabase-local.sh start
docker compose -p "$AGRIFOS_NETWORK" run --rm --no-deps migrate
docker compose -p "$AGRIFOS_NETWORK" run --rm --no-deps migrate alembic check
```

Reemplaza `XXXXXXXX` por el id real. `alembic check` debe informar que no hay nuevas
operaciones. La comparación excluye únicamente el stub externo `auth.users`; conserva
las FKs públicas, el índice parcial único y ON DELETE RESTRICT de las migraciones existentes.
Los cambios legítimos de columnas/índices/FKs de aplicación siguen detectándose.
Investiga cualquier nuevo FAIL sin cambiar Auth ni migraciones históricas para ocultarlo.

Restablecimiento destructivo **solo para un proyecto nuevo de pruebas creado por estos scripts**:

```bash
docker compose -p "$AGRIFOS_NETWORK" stop api migrate
bash scripts/supabase-local.sh destroy-test --confirm-project "$AGRIFOS_NETWORK"
```

Ese comando elimina datos de esa instancia identificada y exige confirmación exacta;
rechaza `agrifos` y recursos sin registro de propiedad. Para una prueba desde vacío puedes
simplemente ejecutar otra vez el driver: genera un proyecto nuevo sin borrar el anterior.
La eliminación de datos personales del entorno de desarrollo queda fuera de este comando.

## Flutter y APK debug

```bash
bash scripts/docker-dev.sh prepare
bash scripts/flutter-container.sh version
bash scripts/flutter-container.sh restore
bash scripts/flutter-container.sh analyze
bash scripts/flutter-container.sh test
# Ejecuta tú la revisión y aceptación de licencias en terminal interactiva:
bash scripts/flutter-container.sh licenses
bash scripts/flutter-container.sh sdk
# Requiere configure tras iniciar Supabase local:
bash scripts/flutter-container.sh apk
```

`tools` permite análisis/pruebas con configuración pública ficticia, sin licencias Android
ni servicios Supabase. `android` incorpora las herramientas; las plataformas y NDK se
provisionan después de la aceptación interactiva. No hay aceptación automática de licencias.
El APK se exporta a `artifacts/agrifos-debug.apk`. Se regeneran wrappers Gradle ausentes
mediante Flutter, sin alterar la configuración versionada.

La app carga `.env` como asset. El filtro solo permite `SUPABASE_URL`,
`SUPABASE_PUBLISHABLE_KEY` y `API_BASE_URL`; rechaza service_role, sb_secret,
credenciales en URLs y variables desconocidas. Un APK exige configuración pública válida.
HTTP local se permite solo en el manifest debug. La firma release no se modifica.

El código se copia desde un montaje de solo lectura a un workspace Linux, excluyendo env
nativos, keystores y cachés Windows. Volúmenes separados conservan workspace (incluida la
clave **debug**), pub, Gradle y SDK. En Linux el script usa UID/GID del colaborador y construye con ese
usuario; si cambia el UID, usa un nombre de proyecto Compose nuevo para cachés nuevas:

```bash
COMPOSE_PROJECT_NAME=agrifos-kevin bash scripts/flutter-container.sh analyze
```

No resuelvas permisos con `privileged` ni cambiando propietario de volúmenes ajenos.

Para instalar y conectar un teléfono Android desde el host con depuración autorizada:

```bash
adb install -r artifacts/agrifos-debug.apk
adb reverse tcp:8000 tcp:8000
adb reverse tcp:54321 tcp:54321
```

Antes de compilar para ese caso, prepara otro archivo público local con ambas URLs
`http://127.0.0.1:<puerto>` y conserva el original del emulador:

```bash
AGRIFOS_CLIENT_ENV=.docker/local/client-usb.env bash scripts/flutter-container.sh apk
```

ADB/emulador/USB/sensor no se verificaron en este equipo. El acceso por LAN **no está
habilitado en este flujo**: los scripts rechazan exposición fuera de loopback. Habilitarlo
requiere una ampliación explícita que revise bindings y firewall para una IP privada;
no basta cambiar las URLs del cliente. No expongas ADB, DB, Studio o claves administrativas
a una red pública. Un proyecto Supabase remoto tampoco es dependencia de este entorno.

## Windows, rutas y problemas frecuentes

- Usa `bash scripts/...sh`; no es necesario Make ni permisos ejecutables Git.
  `.gitattributes` mantiene LF para shell. No guardes estos scripts con CRLF.
- Los scripts convierten rutas a formato Windows para ejecutables nativos y desactivan
  la reescritura MSYS de argumentos del contenedor. Las rutas se citan para admitir espacios.
- WSL puede mejorar el rendimiento de montajes si el checkout reside en su filesystem;
  no reutilices una `.venv`, `.dart_tool`, SDK o caché del otro sistema.
- Si aparece `dockerDesktopLinuxEngine` inexistente, comprueba Docker Desktop y `docker version`.
  Reinstalaciones/cambios de WSL o servicios requieren una decisión del operador.
- Si hay conflictos en 8000 o 54321–54324, identifica el proceso. No detengas recursos ajenos.
  Los puertos Supabase se derivan del config y el issuer debe mantenerse coherente.
- Para `401`, verifica canonical issuer, ES256, audience y JWKS; para `403 mfa_required`,
  completa TOTP. Nunca desactives validaciones para resolver la conexión.
- Si `configure` conserva archivos antiguos, revisa esos archivos localmente sin imprimir
  credenciales. Si rotas claves deliberadamente, considera cachés y sesiones existentes.

## CI y actualizaciones deliberadas

```bash
bash scripts/check-docker.sh static
# Requiere la imagen runtime construida:
bash scripts/check-docker.sh images
```

El primer comando valida Compose sin expandir secretos, sintaxis Bash y Dockerfiles con
Hadolint 2.15.1 verificado por checksum. Los errores bloquean; las advertencias permanecen
visibles. APT no fija paquetes individuales y Hadolint no reconoce el `SHELL` heredado
por la etapa Android. El segundo comando usa Trivy 0.75.0 por digest para analizar la
configuración y la imagen backend runtime real: vulnerabilidades, secretos y configuración.
Los hallazgos HIGH/CRITICAL producen `FAIL`, sin exclusiones. Los informes JSON y el ID
de imagen quedan en `.docker/evidence/scanners/`; el escáner no recibe archivos env ni
acceso al socket Docker. El resultado y las limitaciones constan en el registro de validación.
En la ejecución actual, Trivy aprobó 60 controles para los tres Dockerfiles; no emitió
controles específicos de Compose aunque el archivo se suministró. Compose se valida
con `config --quiet` y revisión de los bindings, perfiles, montajes y variables.
El escáner conserva los informes anteriores en `history/` y verifica el digest de configuración
del archivo exportado contra el informe actual. Ejecuta los escaneos secuencialmente:
comparten `.tools/trivy-cache` y Trivy bloquea su caché durante un análisis.
CI conserva durante 30 días el artifact backend-scanner-summary, incluso cuando el gate
falla. Solo contiene CVEs, paquetes/versiones, contadores y digest; omite matches de
secretos, configuración Env y mensajes crudos. No cambia la condición de fallo.

Trixie ya es la base normal adoptada tras la comparación documentada. El helper
`bash scripts/evaluate-trixie.sh` y sus modos `test`, `scan`, `integration` conservan
tags aislados `agrifos-backend-evaluation:trixie-*`; ahora reproducen el mismo pin
Trixie sin modificar tags normales ni paquetes del lock. Rechazan bases no revisadas.
El driver predeterminado usa la base actual del Dockerfile y devuelve error ante drift;
el escaneo devuelve FAIL mientras persistan HIGH/CRITICAL.

El workflow Docker agrega validaciones sin sustituir los checks nativos existentes:
backend con lock, pruebas/escaneo de imagen, integración Auth aislada y Flutter analyze/test.
El APK permanece pendiente de la revisión humana de licencias y validación manual.
No publica imágenes, no usa secretos de producción ni hace merge.

Para actualizar pins: consulta releases oficiales y manifiestos; verifica checksum/digest;
actualiza juntos versión, checksum y assertions; comprueba compatibilidad con CI/locks;
repite construcción limpia, Auth/migraciones, tests y APK. No actualices paquetes ni regeneres
locks para resolver un fallo de empaquetado sin investigar su causa.

Referencias: [uv Docker](https://docs.astral.sh/uv/guides/integration/docker/),
[Supabase CLI 2.120.0](https://github.com/supabase/cli/releases/tag/v2.120.0),
[Flutter manifest](https://storage.googleapis.com/flutter_infra_release/releases/releases_linux.json),
[defaults Android de Flutter 3.44.9](https://raw.githubusercontent.com/flutter/flutter/3.44.9/packages/flutter_tools/gradle/src/main/kotlin/FlutterExtension.kt),
[AGP 9.0.1](https://developer.android.com/build/releases/agp-9-0-0-release-notes).
