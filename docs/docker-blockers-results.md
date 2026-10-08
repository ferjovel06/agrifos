# Resolución de bloqueantes Docker: resultados

**Registro histórico de N1/S1/evaluación S2.** La fase de finalización posterior
resolvió Alembic y adoptó Trixie, conservando estas evidencias. El resultado vigente
está en [docker-closeout.md](docker-closeout.md); Trivy sigue bloqueado y no hay
aprobación de merge. Los estados de este documento corresponden a su propia fase.

Fecha: 2026-10-08. Rama exclusiva: `chore/docker-environment`.
Base preservada: `a1df7e06943aef78c042340b65edb7e7e4113701`.

**Estado global: INCOMPLETO; sin autorización para integrar en main.**
N1 funciona en Windows/Docker Desktop y S1 corrige los hallazgos Python autorizados,
incluida la vulnerabilidad JWKS confirmada. S2 se evaluó sin sustituir Bookworm.
Persisten el umbral Trivy de Debian, diferencias preexistentes de metadatos Alembic,
la validación completa del host Linux y la aceptación humana de licencias Android.

## Arquitectura y cambios autorizados

Supabase CLI 2.120.0 continúa en el host y administra PostgreSQL, GoTrue/Auth,
Kong y Mailpit. Compose conserva la API, migraciones y tareas separadas sobre la
misma red bridge propia. El adaptador es un proceso nativo temporal que delega
al Docker original; no agrega proxy, servicio permanente, red ni infraestructura remota.
Flutter y el toolchain Android no se actualizaron. `backend/Dockerfile` conserva
Python 3.13.16 slim-bookworm por su digest aprobado.

`supabase-local.sh` captura el Docker original por ruta absoluta, construye/verifica
el adaptador en `.tools/loopback-adapter/<hash-fuentes>/` y modifica PATH solamente
para el hijo Supabase CLI. El preflight invoca el mismo adaptador. Se compila con
Go 1.27.2 fijado por digest en Docker, sin instalar Go en el sistema ni añadir
dependencias Go externas; no se requiere un `go.sum`.

El adaptador reconoce el dialecto de creación del CLI fijado y limita sus operaciones
de create/run/start/restart al proyecto, workdir y bridge seleccionados. Convierte
publicaciones sin IP en `127.0.0.1:host:container`; rechaza IPs explícitas distintas,
publish-all, host networking, sintaxis desconocida y ambigüedades antes de crear.
No reinterpreta los argumentos del comando del contenedor después de la imagen.
Los jobs efímeros de inicialización de CLI 2.120 omiten workdir: solo se permiten
con sus dos etiquetas de proyecto, la red propia, sin binds ni puertos; se añade
la etiqueta workdir antes de delegar. Los servicios conservan create/cp/start y
su entrega de archivos secretos por stdin. No se imprimen argv ni Env completos.

Antes de activar un contenedor se inspeccionan propiedad, red y bindings solicitados.
Después se comprueban los bindings efectivos; un incumplimiento intenta detener
solo el contenedor propio ya verificado. El preflight mantiene su sonda acotada
sin listener, credenciales ni volúmenes y conserva la limpieza por identidad exacta.
Los controles de propiedad y los backups del CLI siguen habilitados.

### Prueba de red real

Los proyectos de integración se generaron dentro de `.docker/integration/`:

| Proyecto | Imagen de backend | Resultado |
|---|---|---|
| `agrifos-it-c3732c0d` | Bookworm | FAIL inicial: el adaptador rechazó el job de inicialización sin workdir; corregido con la regla limitada descrita arriba |
| `agrifos-it-089c52fc` | Bookworm | PASS del recorrido original completo, con reinicio y persistencia |
| `agrifos-it-a4dc954e` | Trixie aislada | PASS funcional; FAIL adicional de `alembic check`, salida global 255 |
| `agrifos-it-2afcd7ca` | Bookworm, driver ampliado final | PASS funcional y auditoría completa; FAIL de `alembic check`, salida global 255 |

En ambas fases de cada recorrido exitoso se inspeccionaron los cuatro contenedores
Supabase y la API. Publicaciones efectivas: Kong `127.0.0.1:54331`, PostgreSQL
`127.0.0.1:54332`, correo `127.0.0.1:54334` y API `127.0.0.1:8010`.
Auth no publica puerto al host. No hubo binding `0.0.0.0`, IPv6 wildcard ni LAN
en los servicios de estos proyectos. `Get-NetTCPConnection` corroboró los cuatro
listeners reales de Windows en `127.0.0.1`, además de la inspección del daemon.

Las pruebas del adaptador se ejecutaron en Linux amd64 dentro del builder y en
Windows con el ejecutable de tests compilado para Windows: **10 pruebas principales
PASS con subcasos**. Cubren puertos, IPv4/IPv6/LAN, argumentos después de la imagen,
propiedad, flags/global options, auxiliares y comprobaciones antes/después de start.
El flujo completo en un host Linux permanece **NOT RUN**: solo existe la distribución
WSL `docker-desktop`; no se instaló una distribución ni se publicó CI para suplirlo.
Las pruebas de parser/metadata no sustituyen la integración real de Windows.

## S1 y vulnerabilidad JWKS

La resolución dirigida cambió exactamente dos versiones:

| Paquete | Antes | Después | Aplicación |
|---|---|---|---|
| PyJWT, conservando extra crypto | 2.13.0 | 2.14.0 | Verificación JWT y descarga JWKS |
| urllib3 | 2.7.0 | 2.8.0 | Dependencia transitiva de fastapi-cli/cloud-cli/sentry-sdk |

Se elevó el mínimo PyJWT y se añadió una constraint uv para urllib3. Los otros
paquetes, cryptography y sus versiones permanecen iguales. El lock también registra
la constraint y una revisión de formato compatible con uv 0.12.2: las imágenes
se construyeron realmente con `uv sync --locked --no-dev` usando ese uv fijado.
La generación usó el uv 0.12.23 ya instalado; no se actualizó el sistema.

**Vulnerabilidad confirmada:** PyJWT 2.13 seguía redirects de la URL JWKS configurada
y aceptaba claves del destino. Dos servidores HTTP efímeros en loopback reprodujeron
la aceptación de un JWT ES256 cuando se esperaba rechazarlo. Firma, issuer, audiencia
y expiración podían ser correctos porque se confiaba en la clave recibida del destino.
El atacante necesita controlar la redirección del endpoint configurado o su trayecto;
un token por sí solo no elige la URL JWKS en este backend. No se observó envío de
credenciales en headers JWKS de la aplicación.

El problema corresponde a
[CVE-2026-102267 / GHSA-9v7f-9g4p-ffgj](https://github.com/jpadilla/pyjwt/security/advisories/GHSA-9v7f-9g4p-ffgj).
La corrección mínima es S1: PyJWT 2.14 usa un opener que rechaza redirects.
No hizo falta modificar `auth.py`, `SUPABASE_JWKS_URL`, issuer ni las verificaciones
ES256/audience/expiration de esta fase. El 503 ya existente se conserva para errores
de transporte JWKS. No se agregó `SUPABASE_JWT_ISSUER`.

La regresión nueva usa HTTP y criptografía reales: 301/302/303/307/308 se rechazan
con 503 y **cero solicitudes al destino**. Esos cinco subcasos fallaron con 2.13
y pasan con 2.14. También se prueban descarga directa, caché, firma/issuer/audience/
expiración, endpoint no disponible y recuperación de una clave rotada. Solo el reloj
del cooldown se controla en esa prueba; HTTP y selección/verificación de claves son reales.

PyJWT 2.14 incorpora un cooldown predeterminado de 30 segundos para kids desconocidos
tras una descarga reciente. Una nueva clave puede esperar ese intervalo; se comprobó
el rechazo temporal y la recuperación posterior. Se conserva `cache_keys=True` y
lifespan 3600: el TTL del conjunto y la LRU sin TTL de claves individuales son capas
distintas, como antes. No se debilitó ni desactivó la protección nueva.

Trivy ya no reporta los seis avisos PyJWT `CVE-2026-102266`, `102267`, `102268`,
`102271`, `102272`, `102273`, ni los dos urllib3 `CVE-2026-97687`, `97689`.
La aplicabilidad y fuentes individuales de la evaluación inicial siguen en
[la propuesta comparativa](docker-blockers-proposal.md). El alcance del escaneo
registrado es HIGH/CRITICAL; no acredita ausencia de avisos de otras severidades.

## S2: evaluación aislada de Trixie

La receta de evaluación sustituye únicamente la línea base del Dockerfile en una
copia ignorada. Pin evaluado:
`python:3.13.16-slim-trixie@sha256:bf44cdfcb76cd3b41e879bc058fc37ec5872002ccfde7fcb765e218cde0cd79c`.
Genera los tres tags `agrifos-backend-evaluation:trixie-test`, `-development` y
`-runtime`. El override Compose de evaluación se usa solo en un proyecto sintético
nuevo; los tags normales y el Dockerfile de Agrifos permanecen Bookworm.

| Medida efectiva | Bookworm + S1 | Trixie + mismo lock |
|---|---|---|
| Python | 3.13.16 | 3.13.16 |
| Debian detectado | 12.15 | 13.7 |
| OpenSSL del intérprete | 3.0.22 | 3.5.7 |
| SQLite del intérprete | 3.40.1 | 3.46.1 |
| Paquetes OS detectados por Trivy | 97 | 87 |
| Docker image inspect `.Size`, bytes | 77,867,985 | 74,444,448 |
| Trivy HIGH / CRITICAL | 53 / 2 | 44 / 0 |
| CVEs OS distintos | 15 | 8 |
| Python HIGH/CRITICAL | 0 | 0 |
| Backend unitarias | 121 PASS | 121 PASS |
| Imports binarios del lock | PASS | PASS |
| API/Auth/JWT/MFA/persistencia reales | PASS | PASS |
| Alembic upgrade/current/repetición | PASS | PASS |
| Alembic check | FAIL | FAIL, mismas diferencias |
| Umbral Trivy | FAIL | FAIL |

`.Size` es el valor informado por este daemon, comparado con el mismo comando;
no representa el uso total con cachés, volúmenes ni todas las capas compartidas.
Trixie reduce ese valor aproximadamente 4.4%. asyncpg, psycopg2-binary, cryptography,
pydantic-core y greenlet importan correctamente; la integración conecta realmente
al mismo PostgreSQL 17 gestionado por la CLI, sin reemplazarlo ni usar mocks.

Trixie elimina del escaneo los avisos de SQLite, gzip, OpenSSL, el mount TOCTOU
`CVE-2026-53613` y zlib/minizip `CVE-2023-45853`. Siguen los cuatro CVEs util-linux
`76642`, `78408`, `78409`, `78410` de 2026, ncurses `CVE-2025-69720`,
systemd `CVE-2026-16742`, libacl `CVE-2026-54369` y perl `CVE-2026-9538`.
Las cuatro familias util-linux ahora aparecen en nueve paquetes, incluido
liblastlog2-2 y login, por lo que quedan 44 entradas reales y no las 40 estimadas.
Las versiones instaladas y campos FixedVersion completos están en los JSON;
Trivy no indica versión corregida Trixie para esas entradas remanentes.

La distinción entre paquete detectado y ruta explotable sigue siendo necesaria:
por ejemplo, Debian considera el aviso minizip de Bookworm no aplicable a su build
zlib y no está instalado libminizip1; otros avisos requieren utilidades ausentes,
privilegios, DTLS o entradas que el backend no usa. Son conclusiones limitadas del
análisis previo, no excepciones al gate ni una demostración general de inexplotabilidad.
No se introdujeron exclusiones Trivy, actualizaciones masivas, mezcla con sid ni
eliminación indiscriminada de librerías del runtime.

**Recomendación:** Trixie ofrece una mejora comprobada y compatibilidad funcional,
pero no cierra el umbral de seguridad. Su adopción sigue requiriendo autorización
posterior y una decisión sobre los HIGH restantes; no se recomienda aprobar main
con estos resultados ni presentar Trixie como solución completa del escaneo.

Se compararon ambas imágenes con Trivy 0.75.0 fijado por digest y la misma base
de datos, UpdatedAt `2026-10-08T15:33:46.578791096Z`. Se aprobaron 60 controles
de configuración de los tres Dockerfiles, sin controles específicos de Compose
emitidos por Trivy. Los informes del runtime no contienen hallazgos de secretos
ni misconfiguración en el alcance analizado. Las imágenes vendor y Flutter no
recibieron un nuevo escaneo integral en esta fase.

IDs runtime finales: Bookworm
`sha256:eb2a9028b864bbc70d29db6ee8bc0a5737f2d881b8133010e59dd6dc77f961e1`;
Trixie `sha256:ca4d45566077b0778501475c6db117efe090cac85974a77d3fe1fb2d5d7a3b57`.
El export se hace por ese ID inmutable. Su config digest se calculó desde manifest.json
del archivo y coincide con Metadata.ImageID de Trivy en ambas imágenes. Los IDs de
índice OCI y de config son diferentes tipos y no se comparan entre sí directamente.
Los intentos anteriores se conservan y un fallo nuevo ya no puede reutilizar su JSON.

## Bloqueante Alembic descubierto

El driver ahora ejecuta `alembic check` además de upgrade/current. Completa las
comprobaciones de persistencia y limpieza sintética aunque haya drift y devuelve
el error global al final. Ambas bases devuelven 255 con las mismas seis operaciones
propuestas por autogenerate:

1. Añadir `auth.users`: es el stub de metadata para resolver la FK; la tabla real
   sí existe y se comprobó con el login y el trigger. env.py no refleja schemas
   externos ni distingue explícitamente esta metadata administrada por Supabase.
2. Eliminar `ix_agronomic_reference_sets_active`: la migración lo crea como índice
   parcial único sobre key WHERE is_active; el modelo no lo declara.
3. Quitar/añadir la FK de stage_id de optimal_requirements y de stage_factors:
   las migraciones tienen ON DELETE RESTRICT y los modelos no declaran ese ondelete.

`backend/alembic/` y `backend/app/models/` son idénticos a origin/main; esta fase
no introdujo esas discrepancias. No se ejecutó stamp, reset, autogenerate revision,
drop ni una migración compensatoria. La interpretación de autogenerate y su
necesidad de revisar metadatos está documentada por
[Alembic](https://alembic.sqlalchemy.org/en/latest/autogenerate.html).

Propuesta acotada, **pendiente de autorización**: identificar solo el stub externo
auth.users para excluirlo de la comparación de objetos administrados por Agrifos;
declarar en el modelo el índice parcial que la migración ya creó y los dos ondelete
RESTRICT con sus nombres existentes. Conservar las migraciones, la tabla Auth real
y la política de borrado existente. Agregar regresiones de esos metadatos y repetir
alembic check e integración en una base nueva y tras reinicio. No proponer el drop
del índice ni retirar RESTRICT para hacer pasar artificialmente la comparación.

## Matriz de validación y evidencia

| Prueba | Estado | Evidencia local principal |
|---|---|---|
| Backend nativo, Python 3.13.5 existente | PASS: 121 | `.docker/evidence/phase2/backend-native-final.txt` |
| Backend Docker Bookworm | PASS: 121 | `backend-docker-final.txt` en phase2 |
| Backend Docker Trixie y imports | PASS: 121 | `trixie-tests-final.txt` en phase2 |
| Git archive 77436cc, checkout limpio con espacios | PASS: build y 121; adaptador verificado | `clean-backend-build.txt`, `clean-backend-tests.txt`, `clean-adapter.txt` en phase2 |
| Infraestructura Docker | PASS: 34, cero skips | `infrastructure-docker-final.txt` en phase2 |
| Infraestructura Windows nativa | PASS: 22; NOT RUN: 12 Linux-only | `infrastructure-native.txt` en phase2 |
| Go Linux/Windows | PASS: 10 principales en cada plataforma | `adapter-build-final.txt` en phase2 |
| Compose quiet, Bash, Hadolint | PASS; advertencias existentes visibles | `static-final.txt` en phase2 |
| Preflight y bindings reales, ambos arranques | PASS | `bindings-initial.jsonl`, `bindings-persistence.jsonl` de cada proyecto |
| Listeners nativos Windows | PASS: cuatro loopback | `windows-listeners-complete.json` en phase2 |
| FastAPI health y PostgreSQL real | PASS | drivers Bookworm/Trixie en phase2 |
| Alembic head b2c4d6e8f901 y migración repetida | PASS | mismos drivers |
| Login, ES256, trigger, token/password inválidos | PASS | mismos drivers |
| MFA TOTP, AAL1 403 y AAL2 200 | PASS | mismos drivers |
| Persistencia de usuario/perfil tras stop/start | PASS | mismos drivers |
| Alembic check y salida del driver ampliado | FAIL: 255 en ambas bases | `integration-bookworm-complete.txt`, `integration-trixie.txt` |
| Trivy runtime Bookworm / Trixie | FAIL: 55 / 44 entradas | `.docker/evidence/scanners/` y `scanners-trixie/` |
| Identidad imagen/informe de ambos escaneos | PASS | runtime-identity.json de cada directorio |
| Flutter analyze y tests, lock conservado | PASS: sin issues; 81 tests | `flutter-analyze.txt`, `flutter-tests.txt` en phase2 |
| Licencias Android, SDK/NDK/APK, ADB/hardware | NOT RUN en esta fase | Pendiente del usuario; no se aceptaron licencias |
| Flujo completo en host Linux y CI remoto | NOT RUN | Sin distribución de desarrollo ni push/PR |
| Studio opcional y pruebas de LAN | NOT RUN en esta fase | Studio no arrancado; LAN no habilitada |

Los tests backend ordinarios siguen usando sus dobles existentes; las regresiones JWKS
HTTP y el driver de integración indicados aquí son reales. Las regresiones de Bash
simulan fallos del daemon para comprobar el guardrail y no se presentan como integración.
Los proyectos/volúmenes se conservaron; solo se retiraron sondas propias y usuarios
sintéticos de los proyectos creados para estas pruebas. El volumen y la red anteriores
`agrifos-it-41e1be45` permanecieron intactos, así como el contenedor ajeno observado.

También se conservaron fallos de preparación: la primera evaluación Trixie omitía
el env de tests y produjo 12 errores de importación; se corrigió usando el entrypoint
nativo existente y después pasaron las 121 pruebas. Un intento paralelo Trivy falló
por el lock de caché y no cuenta como escaneo completado; la repetición secuencial
produjo el informe vigente. El primer fixture Go usaba un path Unix en Windows;
se hizo portable antes de la validación final. No se convirtieron esos errores en PASS.

Los JSON públicos de inspección contienen solo nombres, IDs de imagen y puertos.
Los env/signing keys/estado de credenciales locales siguen ignorados y no se publican.
Se eliminaron los archivos de estado de usuarios sintéticos al completar su limpieza;
se preservaron volúmenes y claves locales para poder inspeccionar/repetir el entorno.

## Archivos de esta fase

| Archivos | Cambio |
|---|---|
| backend/pyproject.toml, backend/uv.lock | Solo versiones PyJWT/urllib3 y restricciones necesarias |
| backend/tests/test_auth_jwks_http.py | Regresiones con transporte HTTP y ES256 reales |
| docker/loopback-adapter/Dockerfile, go.mod, main.go, main_test.go, signals_linux.go, signals_windows.go | Builder fijado, adaptador nativo, aislamiento y tests multiplataforma |
| .gitattributes | Fuentes del adaptador con LF consistente entre hosts |
| scripts/install-loopback-adapter.sh, scripts/supabase-local.sh | Bootstrap/verificación local y PATH limitado al CLI; preflight conservado |
| docker/audit_bindings.py, docker/tests/test_binding_audit.py | Auditoría fail-closed de inventario y bindings, con regresiones |
| docker/verify_scan_identity.py, scripts/check-docker.sh | Identidad de imagen real, historia de informes y lint del adaptador |
| scripts/test-docker-integration.sh | Evidencia de bindings/imágenes, Alembic check y variante aislada de evaluación |
| scripts/evaluate-trixie.sh | Build/test/scan/integration separados de las imágenes normales |
| docs/docker.md, docker-validation.md, docker-blockers-proposal.md, docker-blockers-results.md | Guía vigente, contexto histórico y este informe |

## Comandos de uso y reproducción

Desde la raíz del checkout, en Git Bash para Windows o Bash en Linux x86_64:

```bash
bash scripts/install-supabase.sh
bash scripts/docker-dev.sh build
bash scripts/supabase-local.sh start
bash scripts/docker-dev.sh configure
bash scripts/docker-dev.sh up
bash scripts/docker-dev.sh health
```

El adaptador se prepara automáticamente al invocar supabase-local; también puede
verificarse por separado con `bash scripts/install-loopback-adapter.sh`.
Para parar preservando datos: `bash scripts/docker-dev.sh stop` y después
`bash scripts/supabase-local.sh stop`. No usar prune, reset ni down -v.

```bash
docker compose run --rm --no-deps -T backend-unit
docker compose run --rm --no-deps -T backend-unit python -m unittest discover -s /checks/tests -v
bash scripts/check-docker.sh static
bash scripts/check-docker.sh images
bash scripts/test-docker-integration.sh
bash scripts/flutter-container.sh analyze
bash scripts/flutter-container.sh test
```

Actualmente images devuelve FAIL por Debian y el driver devuelve FAIL por Alembic;
son resultados esperados de los bloqueantes documentados, no checks aprobados.
Los puertos 54331–54334 y 8010 deben estar disponibles para el proyecto de prueba.
Cada invocación genera un proyecto nuevo y conserva sus volúmenes al terminar.

```bash
bash scripts/evaluate-trixie.sh build
bash scripts/evaluate-trixie.sh test
bash scripts/evaluate-trixie.sh scan
bash scripts/evaluate-trixie.sh integration
```

Ejecutar scans secuencialmente por la caché compartida. El usuario deberá ejecutar
personalmente `bash scripts/flutter-container.sh licenses` en terminal interactivo
antes de las tareas Android; este agente no ejecutó ni automatizó su aceptación.

## Commits y estado Git

| Commit | Conventional Commit |
|---|---|
| 9f0dda5 | fix(auth): block JWKS redirects with targeted dependency updates |
| cda892c | ops(supabase): enforce loopback bindings before container startup |
| 3e65924 | test(docker): preserve scan evidence and report real migration drift |
| 77436cc | build(docker): add isolated Debian Trixie evaluation workflow |
| Este informe | docs(docker): report validated blocker fixes and remaining failures |

La rama queda 15 commits por delante de origin/main contando los diez anteriores,
con los cambios de esta fase comprometidos y el working tree limpio. main, origin/main
y chore/backend-audit conservan la base indicada al inicio. No hubo push, merge ni PR.
Las imágenes, cachés, archivos locales ignorados y volúmenes de pruebas no forman
parte del commit. `git log -5 --oneline` identifica también el hash del commit del informe.

Bloqueantes restantes: decisión y remediación de Debian/Trivy; autorización para
alinear la metadata Alembic; revisión humana de licencias y validación Android;
ejecución completa del flujo en un host Linux. S2 y la integración en main siguen
requiriendo aprobación posterior, y no se presume el resultado de CI sin ejecutarlo.
