# Informe técnico y validación de Docker

**Registro histórico de la fase inicial.** La fase posterior corrigió Alembic y adoptó
Trixie con Python/lock conservados; la integración real pasa en Windows. Trivy sigue
en FAIL y Android/CI requieren intervención. Consulta el
[informe vigente y evidencia](docker-closeout.md) y el
[registro de riesgos](docker-security-risk-register.md).
El resto de este documento conserva el registro de la fase inicial; sus estados
describen aquella ejecución y no sustituyen los resultados posteriores.
Los informes Trivy originales se preservaron en
`.docker/evidence/phase2/baseline-scanners/`; `scanners/` contiene el análisis vigente.

Fecha: 2026-10-08. Base: `a1df7e06943aef78c042340b65edb7e7e4113701`.
Rama: `chore/docker-environment`, creada desde `origin/main` actualizado.
**Estado: INCOMPLETO. Backend y Flutter tools tienen pruebas reales aprobadas;
Supabase está bloqueado en el Docker Desktop probado y el análisis de vulnerabilidades falla.**
El APK sigue pendiente de licencias y compilación. No se declara un entorno completo
reproducible ni compatibilidad universal.

## Plataforma y versiones efectivas

Windows x64 build 26300.9457, PowerShell 7.6.5, Git Bash 5.2.37 y Git 2.51.2.
Docker Desktop 4.55.0 (213807), cliente/servidor 29.1.3, Linux amd64,
Compose 2.40.3-desktop.1 y WSL 2.6.3. El daemon finalmente arrancó mediante el Desktop
ya instalado, sin instalar/reconfigurar componentes del sistema. Recursos observados:
8 CPU y aproximadamente 12.22 GiB de memoria disponibles para Docker.

| Entorno | Versiones comprobadas |
|---|---|
| Backend development/test/runtime | Python 3.13.16; Uvicorn 0.52.1; usuario efectivo UID/GID 10001 |
| Development/test | uv 0.12.2; venv Linux `/opt/venv` |
| Runtime | Sin uv ni pip; APP_DEBUG=false y FastAPI debug=false; imports efectivos aprobados |
| Dependencias runtime observadas | PyJWT 2.13.0, SQLAlchemy 2.0.51 y urllib3 2.7.0, tomadas del lock |
| Flutter tools/android | Flutter 3.44.9, Dart 3.12.2, Temurin Java 17.0.20.1+1; UID/GID 1000 |
| Android tooling descargado | CLI 22.0 y archivo Platform Tools 37.0.1 con SHA256 verificado |
| Android configuración conservada | Gradle 9.1.0, AGP 9.0.1, Kotlin 2.3.20; SDK 36, Build Tools 36.0.0, NDK 28.2.13676358; compilación pendiente |
| Supabase CLI Windows/Linux | 2.120.0; ambos ejecutables autónomos comprobados y archivos de distribución con SHA256 verificado |
| Supabase bootstrap observado | Postgres 17.11.0.004, GoTrue 2.197.0, Kong 2.8.1, Mailpit 1.31.3 |
| Herramientas de análisis | Hadolint 2.15.1 con checksum; Trivy 0.75.0 por digest |
| Herramientas nativas existentes | Python 3.13.5, uv 0.12.23; Flutter nativo ausente |

Python/uv/JDK/Trivy tienen digest fijado; Flutter y archivos Android/CLI tienen
checksums fijados y contrastados con fuentes oficiales. Las dependencias de aplicación
conservan sus lockfiles. APT y tags de servicios gestionados por Supabase no constituyen
un snapshot inmutable de todas las dependencias externas. No se promete identidad bit a bit
ni primera instalación offline. Linux host/Engine es objetivo del CI y no está validado
como plataforma completa; el instalador Linux se ejecutó realmente dentro de Ubuntu 24.04.5.

## Arquitectura implementada y archivos

Supabase CLI en el host gestiona DB, Auth, gateway y correo; Studio es opcional.
Compose comparte una sola red necesaria para API/migraciones y Supabase, ejecuta
migraciones explícitas antes de la API y separa tareas unitarias, integración y Flutter.
Flutter usa el bridge Docker existente para descargas y volúmenes Linux para sus cachés.
No hay Docker socket en la aplicación, servicios privilegiados, proxy nuevo ni infraestructura remota.

El backend conserva `SUPABASE_URL` pública como origen del issuer. El único ajuste
de autenticación de aplicación es `SUPABASE_JWKS_URL` opcional para la descarga por DNS
interno: loopback dentro del contenedor no alcanza al Auth del host. No se añadió
`SUPABASE_JWT_ISSUER`. ES256, firma, expiración, audiencia e issuer siguen verificándose.
La separación está cubierta por regresiones; el recorrido con token emitido por Auth
real permanece pendiente. Las claves ES256 locales se generan en archivos ignorados.

| Archivos añadidos/modificados | Propósito |
|---|---|
| `backend/Dockerfile`, `backend/.dockerignore` | Targets development/test/runtime; instalación locked; runtime mínimo y no root |
| `backend/app/core/config.py`, `backend/app/core/auth.py`, `backend/tests/test_auth_config.py` | Endpoint JWKS interno con defaults compatibles y 9 regresiones JWT |
| `compose.yaml` | Migración, API, runtime opcional, unit/integration y herramientas Flutter independientes |
| `scripts/install-supabase.sh`, `scripts/supabase-local.sh`, `supabase/config.toml` | CLI local verificada, propiedad de recursos, claves locales, MFA y controles de arranque/binding |
| `scripts/docker-dev.sh`, `docker/configure.py`, `docker/readiness.py` | Preparación idempotente, env por stdin, espera limitada y comandos cotidianos |
| `scripts/test-docker-integration.sh`, `docker/integration_setup.py`, `docker/integration.py` | Driver exclusivamente para un proyecto nuevo: migraciones, Auth, MFA y persistencia reales |
| `docker/tests/` | Regresiones de env, destinos aislados y preflight seguro; dobles identificados explícitamente |
| `docker/flutter/.dockerignore`, `docker/flutter/Dockerfile`, `docker/flutter/entrypoint.sh`, `scripts/flutter-container.sh` | Toolchain Linux, workspace/cachés aislados, lock estricto, licencias interactivas y exportación debug |
| `docker/client.env.example`, `docker/flutter/client.env.example` | Configuración pública ficticia para análisis/tests, sin credenciales administrativas |
| `app_flutter/android/app/src/debug/AndroidManifest.xml` | HTTP local permitido únicamente en debug |
| `.github/workflows/docker.yml`, `.hadolint.yaml`, `scripts/check-docker.sh` | CI adicional, lint y escaneo de imagen/configuración con fallo visible |
| `.gitignore`, `README.md`, `docs/docker.md`, este informe | Exclusión de secretos/artefactos y guía de incorporación/validación |

`render.yaml`, CI nativo, código Flutter funcional, versiones del producto,
manifiestos/locks de dependencias y migraciones históricas permanecen intactos.
No se instalaron/reconfiguraron componentes del sistema, aceptaron licencias SDK,
usaron credenciales de producción ni borraron volúmenes preexistentes.

## Matriz de pruebas

| Validación | Resultado | Evidencia y límite |
|---|---|---|
| Repo/base/rama y refs protegidas | PASS | main, origin/main y chore/backend-audit mantienen el SHA base |
| Docker daemon | PASS | Client y Server Linux amd64 respondieron; indisponibilidad inicial resuelta |
| Compose/sintaxis Bash | PASS | Config quiet y los 8 scripts comprobados individualmente |
| Hadolint | PASS | Sin errores según política; advertencias APT y SHELL heredado Android visibles, sin supresión |
| YAML del workflow Docker | PASS | Tres jobs y permisos contents:read; ejecución remota pendiente |
| Lock Python | PASS | `uv lock --check --offline`; `uv sync --locked` durante build |
| Suite backend nativa y Docker | PASS | 116 pruebas: 107 existentes + 9 nuevas; ejecutor unittest original conservado |
| Infraestructura env/destinos | PASS | 18 pruebas nativas y en Docker; sin red; permisos POSIX 600 comprobados en Linux |
| Regresiones del preflight | PASS | 12 pruebas nuevas Linux; total infraestructura Docker: 30 PASS, cero skips. Windows nativo: 18 PASS y 12 skips explícitos; Docker/CLI falsos sin red |
| Construcción targets backend y Flutter/Android tools | PASS | Cinco imágenes finales construidas realmente; no depende de SDK/.venv del host |
| Construcción desde archivo Git limpio | PASS | Archivo de d64d1ed en ruta con espacios; cinco targets, sin .venv/env/SDK personales; caché BuildKit reutilizada |
| Versiones/runtime no root/imports | PASS | Versiones efectivas de la tabla; runtime UID 10001; /opt/venv y APP_DEBUG=false |
| Instalación CLI Windows/Linux e idempotencia | PASS | Descargas verificadas; segundo arranque del instalador preserva binarios; Linux en contenedor sin socket |
| Bootstrap Supabase y publicación restringida | FAIL | Instancia nueva inicia bootstrap, pero Mailpit publica 0.0.0.0 y ::; guard detiene la prueba |
| Preflight real del binding | PASS | Rechazo esperado de wildcard antes de Auth/DB/mail; sonda propia eliminada |
| Compatibilidad loopback de este daemon/CLI | FAIL | Sonda mínima reproduce incumplimiento del default de bridge; ninguna configuración del sistema cambiada |
| Generación local ES256/secretos ignorados | PASS | Claves nuevas generadas sin sobrescribir; sanitizer con fixtures; valores no versionados |
| Grafo Alembic/compilación Python | PASS | Un único head b2c4d6e8f901; esto no demuestra migración real |
| API real /health y /health/db | NOT RUN | Bloqueadas por arranque Supabase; tests unitarios de health usan mocks |
| Migraciones desde Supabase vacío / alembic check | NOT RUN | No se alcanzó Alembic; ningún stamp/reset ni modificación de Auth |
| Usuario/login/JWKS/invalid-token/MFA reales | NOT RUN | Driver preparado; el fallo de binding precedió a esas comprobaciones |
| Reinicio/persistencia/API reload | NOT RUN | Requiere el stack real sin el bloqueo de binding |
| Flutter analyze | PASS | Restauración `--enforce-lockfile`; No issues found |
| Flutter test | PASS | 81 pruebas reales aprobadas dentro de Docker |
| Flutter permisos/montajes/cachés | PASS | UID1000, fuente ro y escritura/exportación en artifacts con ese UID; sin cambios del host |
| Configuración pública y manifest debug | PASS | 8 fixtures del filtro público y rechazo de claves administrativas; XML válido |
| Control de licencias Android | PASS | Tarea sdk rechaza instalación con licencias pendientes; no se aceptó ninguna |
| SDK plataformas/NDK y APK debug | NOT RUN | Falta revisión/aceptación humana de licencias; compatibilidad completa de plugins no confirmada |
| Emulador/instalación APK/ADB/OTG/sensores/LAN | NOT RUN | Hardware/host; LAN no habilitada |
| Trivy configuración Dockerfiles | PASS | 40 controles aprobados en dos Dockerfiles; Compose se suministró pero Trivy no emitió controles de ese archivo |
| Trivy runtime vulnerabilidades | FAIL | 60 HIGH + 3 CRITICAL; 63 entradas, 23 avisos distintos |
| Trivy runtime secretos/misconfiguración | PASS | Cero hallazgos del escáner en esa imagen; no es garantía absoluta ni escaneo de todas las imágenes vendor |
| CI GitHub/actionlint | NOT RUN | Sin push/PR; no se declaró ningún check remoto aprobado |

Las nueve regresiones JWT usan firmas ES256 reales y verifican expiración, audiencia,
issuer y algoritmo; sustituyen la descarga JWKS. Los dobles de las pruebas de preparación
no cuentan como Auth real. La suite preexistente conserva sus mocks.
Los ajustes iniciales del harness Linux (SDK ro y tmpfs noexec) quedaron registrados;
la ejecución final del instalador usa un tmpfs ejecutable y terminó correctamente.
La comprobación limpia repitió backend (116), infraestructura (30) y Flutter (81),
además de analyze y los wrappers prepare/build. El ajuste posterior del escáner afecta
solo a su script; los archivos de construcción y aplicación no cambiaron.

Evidencia local ignorada: `.docker/clean-build.log`, `clean-backend-unit.log`,
`clean-infrastructure-unit.log`, `clean-flutter-analyze.log`, `clean-flutter-test.log`,
`linux-cli-validation.log`, `evidence/supabase-binding.txt` e `evidence/scanners/`.
Los logs no se adjuntan al CI ni se publican; los archivos privados generados se conservan
localmente para diagnóstico. El escáner exporta el ID inspeccionado, evitando que una
construcción concurrente cambie la imagen evaluada al reemplazar un tag.

## Bloqueo de Supabase y estado de recursos

La primera integración real creó solo `agrifos-it-41e1be45` (puertos 54331–54334/API8010).
La CLI completó bootstrap, pero el guard detectó `0.0.0.0:54334` y `:::54334` en Mailpit.
Una sonda mínima con el runtime y publicación sin IP reprodujo el binding wildcard sobre
la misma red, cuyo `com.docker.network.bridge.host_binding_ipv4` era `127.0.0.1`.
El preflight nuevo comprueba esto antes de lanzar Auth/DB/mail y falla sin abrir un listener.

Docker documenta esa opción como default de publicaciones sin IP; la observación del
runtime probado contradice el comportamiento esperado. No se generaliza a todos los
daemons ni plataformas. [Docker bridge](https://docs.docker.com/engine/network/drivers/bridge/#default-host-binding-address)

La CLI 2.120.0 emite `hostPort:containerPort` y no ofrece un flag de host-bind en start;
`SUPABASE_SERVICES_HOSTNAME` afecta URLs, no publicaciones. Se verificó el código fijado:
[docker-create-args](https://raw.githubusercontent.com/supabase/cli/v2.120.0/apps/cli/src/command-internal/db-bootstrap/docker-create-args.ts),
[Kong](https://raw.githubusercontent.com/supabase/cli/v2.120.0/apps/cli/src/commands/start/services/kong.service.ts).
No se instaló un wrapper Docker ni se cambió la versión CLI/topología/daemon para eludirlo.
Resolverlo requiere una decisión adicional sobre una adaptación local del lanzador o
una configuración del runtime revisada y autorizada por el operador.

No quedan contenedores Supabase ni sondas. El stack por defecto `agrifos` nunca se inició.
Se conservaron el volumen `supabase_db_agrifos-it-41e1be45`, su red sin attachments,
los archivos de claves y la evidencia ignorada. Los volúmenes Flutter propios contienen
workspace/pub/Gradle/SDK tools; no contienen un SDK licenciado ni un APK generado.
Solo se eliminaron sondas nuevas y una red Compose vacía creada durante esta tarea y
hecha innecesaria al reutilizar el bridge para Flutter. No se borraron recursos preexistentes.

## Hallazgos de seguridad

Trivy bloquea por HIGH/CRITICAL sin exclusiones. Retirar únicamente pip y sus librerías
incluidas de la base redujo el resultado de 67 entradas a 63. Las dependencias de aplicación
en `/opt/venv` no cambiaron y el runtime se reconstruyó y comprobó después.

| Origen restante | Entradas | Tratamiento |
|---|---:|---|
| Base Debian fijada | 55 (53 HIGH, 2 CRITICAL) | El informe no indica FixedVersion; requieren revisar base y aplicabilidad, sin cambios automáticos |
| PyJWT 2.13.0 del lock existente | 6 (5 HIGH, 1 CRITICAL) | Trivy indica corrección en 2.14.0; actualización requiere aprobación |
| urllib3 2.7.0 del lock existente | 2 HIGH | Trivy indica corrección en 2.8.0; actualización requiere aprobación |

El aviso crítico PyJWT CVE-2026-102268 requiere mezclar HMAC y algoritmos asimétricos.
Por inspección infiero que ese vector no aplica al ES256 exclusivo de Agrifos; no implica
que todos los avisos PyJWT sean inocuos. El aviso de redirects JWKS merece revisión separada.
[Aviso del mantenedor](https://github.com/jpadilla/pyjwt/security/advisories/GHSA-ffc3-869f-jxw9),
[JWKS](https://github.com/jpadilla/pyjwt/security/advisories/GHSA-9v7f-9g4p-ffgj)

Las otras entradas críticas son SQLite CVE-2025-7458 y zlib CVE-2023-45853. Debian marca
esta última como MiniZip no compilado en Bookworm; se conserva el resultado bruto sin
suprimirlo ni declarar el escaneo aprobado. [Debian zlib](https://security-tracker.debian.org/tracker/CVE-2023-45853)

Los JSON del escáner, imagen inspeccionada y detalle por paquete/CVE están en
`.docker/evidence/scanners/`, ignorado. El CI agregado fallará mientras estos hallazgos
no se resuelvan o se acuerde una política revisada; no se añadieron excepciones.
El escaneo final exportó el ID inmutable
`sha256:d306c20ce70be7ecc3186a04d788a06116ab5ae62103bf91636a86c1fd0e0137`;
la configuración Linux amd64 tiene SHA256
`6d8c2cb5ba34ef6c4a02e3b1d909df74f75126d252f6b4f48d84e55b4462ff10`.
Se calculó ese hash desde el archivo Docker exportado por ID y se comprobó contra Trivy,
incluidas sus capas. El índice OCI y el hash de configuración son identificadores distintos;
la verificación queda en `runtime-identity.json` junto a los informes.

## Comandos de uso y próximos pasos

Guía completa, URLs, Windows, licencias, persistencia y diagnóstico:
[docker.md](docker.md). Comandos independientes que sí se comprobaron:

```bash
bash scripts/docker-dev.sh prepare
bash scripts/docker-dev.sh build
bash scripts/docker-dev.sh test
bash scripts/check-docker.sh static
bash scripts/flutter-container.sh version
bash scripts/flutter-container.sh analyze
bash scripts/flutter-container.sh test
```

Para completar el entorno: resolver el binding manteniendo loopback; repetir integración
desde un proyecto nuevo, health, Alembic/drift, Auth/MFA, persistencia y reload; revisar
licencias y compilar/instalar APK; acordar las correcciones de seguridad y repetir el escaneo.
No se aceptan licencias en nombre del colaborador. No se solicita publicación hasta
decidir esos bloqueos. Push y PR requieren tu autorización posterior y explícita.

## Commits y Git

| SHA | Commit |
|---|---|
| e680b44 | build(backend): add locked Docker image targets |
| 5c4ca39 | fix(auth): support internal JWKS without changing token validation |
| d59afd1 | build(flutter): add isolated Android tooling with license gates |
| 2d01b0f | build(backend): remove unused package installer from runtime |
| 9d05074 | ops(dev): orchestrate local Supabase with fail-closed startup checks |
| 9139f37 | test(docker): cover isolated configuration and startup guardrails |
| d64d1ed | ops(ci): validate container workflows and image security |
| 58bc84f | ops(ci): scan the inspected immutable runtime image |

El commit de documentación agrega la guía y este informe; su SHA se obtiene con
`git log -1 --oneline`, dado que un archivo no puede incluir el SHA de su propio commit.
`main`, `origin/main` y `chore/backend-audit` mantienen el SHA base. No hubo push, PR,
merge ni publicación de imágenes. La identidad Git y los remotos se conservaron.
El cierre local consta de 9 commits en esta rama y 32 archivos añadidos/modificados frente
a la base. `git status --short` queda vacío después del commit de documentación; las
herramientas, claves, volúmenes y evidencia descritos permanecen locales e ignorados.
