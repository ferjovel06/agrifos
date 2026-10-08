# Finalización de Docker: validación y entrega

Fecha: 2026-10-08. Rama: `chore/docker-environment`.
**Estado: INCOMPLETO. No se recomienda merge.** Alembic y la integración real están
resueltos; Trixie fue adoptada bajo autorización. Trivy continúa en FAIL, y la
aceptación personal de Android sigue pendiente. El
[PR #76](https://github.com/ferjovel06/agrifos/pull/76) está publicado como Draft.

Este documento sustituye los estados vigentes de los informes anteriores, que se
conservan como evidencia histórica. [Guía operativa](docker.md) y
[registro de riesgos por CVE](docker-security-risk-register.md).

## Diagnóstico y correcciones

Se inspeccionó Git antes de editar: rama limpia, 15 commits propios existentes y
remoto `https://github.com/ferjovel06/agrifos.git`. Fetch encontró `origin/main`
en `33e53a3`, con fertilización orgánica y documentación nuevas. Se incorporaron
mediante un merge en la rama de trabajo, preservando los commits. El conflicto del
README se resolvió conservando el entrypoint de pruebas que prepara su entorno.
No se modificaron las ramas locales main ni chore/backend-audit.

### Alembic

La inspección PostgreSQL del proyecto retenido `agrifos-it-2afcd7ca` confirmó:

| Diferencia informada | Esquema real | Corrección |
|---|---|---|
| Añadir auth.users | Tabla existente, gestionada por Supabase | Excluir únicamente ese stub externo con include_object; no activar introspección masiva de schemas Supabase |
| Eliminar ix_agronomic_reference_sets_active | Índice UNIQUE sobre key WHERE is_active | Declarar el índice parcial existente en AgronomicReferenceSet |
| Recrear FK stage_id de optimal_requirements | fk_optimal_requirement_stage_template, ON DELETE RESTRICT | Declarar mismo nombre y política en el modelo |
| Recrear FK stage_id de stage_factors | fk_stage_factor_stage_template, ON DELETE RESTRICT | Declarar mismo nombre y política en el modelo |

No existía DDL de aplicación que justificara una nueva migración: las migraciones
ya expresaban el esquema deseado y eran los modelos los que diferían. Se corrigió
la metadata y la comparación; las migraciones históricas se conservaron íntegramente.
No hubo reset, stamp, drop de tablas/índices, reescritura histórica ni borrado de datos.
La base retenida tenía una referencia agronómica y un cultivo; ambos continuaron presentes.

`alembic check` pasa sobre esa base, sobre proyectos nuevos y tras reinicio.
El head continúa `b2c4d6e8f901`. Tres regresiones backend protegen el alcance del filtro,
el índice y RESTRICT. Una comprobación PostgreSQL en transacción de solo lectura
verifica adicionalmente que modificar columnas/índices/FKs en una copia temporal
de metadata produce diferencias detectables. No modifica la base.

### Imagen y seguridad

Se adoptó `python:3.13.16-slim-trixie` por digest
`sha256:bf44cdfcb76cd3b41e879bc058fc37ec5872002ccfde7fcb765e218cde0cd79c`.
Conserva Python 3.13.16, uv 0.12.2 y todas las versiones del lock, incluidas PyJWT 2.14.0
y urllib3 2.8.0. `uv pip check` verificó compatibilidad de 53 paquetes instalados.

| Medida | Bookworm | Trixie |
|---|---|---|
| Python | 3.13.16 | 3.13.16 |
| Debian detectado | 12.15 | 13.7 |
| OpenSSL / SQLite | 3.0.22 / 3.40.1 | 3.5.7 / 3.46.1 |
| Size de Docker inspect, bytes, imágenes comparadas | 77,871,349 | 74,447,800 |
| Paquetes OS detectados | 97 | 87 |
| Trivy HIGH / CRITICAL | 53 / 2 | 44 / 0 |
| CVEs distintos | 15 | 8 |
| Vulnerabilidades Python HIGH/CRITICAL | 0 | 0 |
| Backend | 133 PASS | 133 PASS |
| Integración real y Alembic | PASS | PASS |
| Gate seguridad | FAIL | FAIL |

El tamaño usa la misma medida del mismo daemon, no el espacio total con volúmenes
y cachés. Trixie reduce esa medida aproximadamente 4.4%, elimina los CRITICAL
reportados y conserva compatibilidad funcional. Esto justifica la adopción, pero
no aprueba la seguridad ni la integración en main.

Compose añade cap_drop ALL y no-new-privileges a API/desarrollo/runtime/migrate.
Se comprobaron UID 10001, NoNewPrivs=1 y CapBnd=0 en procesos reales.
No se aplicaron exclusiones, ajustes de severidad, paquetes sid ni eliminación
forzada de componentes esenciales. Los ocho CVEs pendientes y su aplicabilidad,
versiones corregidas fuera de Trixie y decisión pendiente están en el registro de riesgos.

Durante una reconstrucción concurrente, el primer escaneo adoptado produjo el JSON
pero falló su helper de identidad porque el OCI index local había dejado de existir.
Ese intento se conserva como FAIL. La corrección usa un Python base fijado por digest
para verificar el archivo exportado y el digest del informe, sin ejecutar el ID local.
Tres regresiones rechazan digest alterado/manifiesto ambiguo y permiten verificar
un archivo sin acceso a Docker. La repetición confirmó identidad PASS; el gate sigue
FAIL por los 44 HIGH. No se reutilizó un informe viejo para ocultar ese fallo.

Imagen adoptada escaneada por ID inmutable:
`sha256:1f0022c53c981e6caa63586e1091b9dbc2e0e452757f02a75d1c48b4acc79a7b`.
El digest de configuración extraído del archivo y Metadata.ImageID de Trivy coinciden:
`sha256:25dcb2e7c13bfef791a8d1b807d5e2d0541595eb1f314178cb57a833540013d5`.
Los dos tipos de digest no se confunden entre sí.

## Arquitectura definitiva

Supabase CLI 2.120.0 permanece en el host, instalada por checksum dentro del checkout.
Gestiona PostgreSQL 17, GoTrue/Auth, Kong y Mailpit, con Studio opcional. El adaptador
local compilado con Go en Docker limita cada publicación a 127.0.0.1, conserva
propiedad de proyecto/workdir y verifica antes/después del arranque. El preflight sigue activo.
Compose ejecuta migrate antes de API sobre una única red propia compartida con Supabase.
No se añadieron proxies, servicios permanentes, redes adicionales ni infraestructura remota.

Se conserva issuer público derivado de SUPABASE_URL y JWKS por DNS interno.
Solo ES256, audience authenticated, firma, issuer, expiración y MFA existentes.
Las pruebas de redirección JWKS usan HTTP real y verifican 301/302/303/307/308,
503 y cero solicitudes al destino. Las pruebas de claims del driver firman JWT
con la clave recién generada del proyecto sintético, montada solo en la tarea de test.
Así se comprueba el rechazo de claims con firma válida, sin modificar Auth ni usar mocks.
No se montan credenciales de producción ni claves release.

Flutter conserva 3.44.9/Dart 3.12.2/JDK 17; Gradle 9.1.0, AGP 9.0.1 y Kotlin 2.3.20
del proyecto. SDK 36/Build Tools 36.0.0/NDK 28.2.13676358 coinciden con los defaults
de [Flutter](https://raw.githubusercontent.com/flutter/flutter/3.44.9/packages/flutter_tools/gradle/src/main/kotlin/FlutterExtension.kt)
y los requisitos de [AGP](https://developer.android.com/build/releases/agp-9-0-0-release-notes).
La configuración Android y los locks permanecen iguales respecto al main incorporado.
La compatibilidad de compilación final sigue NOT RUN hasta la revisión humana de licencias.

## Validación local y evidencia

Host: Windows 11 Pro x64/Git Bash/Docker Desktop 4.55.0, Engine 29.1.3 y Compose 2.40.3.
Se usó `git archive 4474762` en `.docker/closeout clean-c8/`: solo archivos versionados,
sin env personales, claves, .venv, SDK nativo ni .tools. Docker reutilizó capas verificadas;
no se afirma construcción bit a bit idéntica ni desde caché vacía. La CLI se descargó
de nuevo y el adaptador se preparó dentro de ese checkout. Flutter usó un namespace
de volúmenes nuevo `agrifos-closeout-clean`, restaurando con --enforce-lockfile.

| Validación | Resultado | Evidencia local en .docker/evidence/closeout |
|---|---|---|
| Backend Windows Python 3.13.5 existente | PASS, 133 tests | backend-native.txt |
| Backend Bookworm / Trixie evaluada | PASS, 133 cada uno | backend-bookworm.txt, backend-trixie.txt |
| Build Trixie desde Git archive con espacios | PASS, test/development/runtime | clean-build.txt, clean-checkout-ref.txt |
| Backend checkout limpio | PASS, 133 | clean-backend-tests.txt |
| Infraestructura antes/después de regresiones de escaneo | PASS, 34 / 37 / 39 | clean-infrastructure.txt, infrastructure-final.txt |
| Regresiones de identidad Windows nativo | PASS, 3 | scan-proof-native.txt |
| Adaptador Windows / Linux amd64 en contenedor | PASS, 10 principales cada uno, con subcasos | clean-integration.txt, adapter-linux.txt |
| Compose quiet, Bash y Hadolint | PASS, advertencias documentadas | static.txt |
| Base retenida con datos, Alembic | PASS, sin DDL ni pérdida de las filas comprobadas | schema-before.txt, alembic-existing-after.txt, data-existing-after.txt |
| Driver nuevo Bookworm | PASS | integration-bookworm.txt, proyecto agrifos-it-196e99e3 |
| Driver ampliado Trixie aislada | PASS | integration-trixie.txt, proyecto agrifos-it-d671b5f3 |
| Driver desde checkout limpio con base adoptada | PASS | clean-integration.txt, proyecto agrifos-it-c70ae774 |
| Supabase bindings iniciales/tras reinicio | PASS, 5 contenedores y 4 publicaciones loopback | bindings-initial/persistence.jsonl en cada proyecto |
| Listeners TCP Windows iniciales/tras reinicio | PASS, cuatro 127.0.0.1 | windows-listeners-initial/persistence.json en los proyectos Trixie |
| FastAPI /health y /health/db, PostgreSQL real | PASS | drivers anteriores |
| Alembic upgrade/current/check/repetición | PASS, head b2c4d6e8f901 | drivers anteriores |
| Login ES256/trigger/firma incorrecta/contraseña inválida | PASS | drivers anteriores |
| JWT firmado: audience/issuer/exp incorrectos; HS256/malformado | PASS, 401 | drivers Trixie y limpio |
| Redirecciones JWKS y rotación de kid | PASS, HTTP/criptografía reales | tests auth_jwks_http dentro de backend-* |
| TOTP MFA: AAL1 403, AAL2 200 | PASS | drivers anteriores |
| Persistencia tras stop/start y migración repetida | PASS | drivers anteriores |
| Runtime sin reload/uv, imports binarios y controles de privilegios | PASS | runtime-up.txt, runtime-auth.txt |
| Runtime real health/JWT/MFA | PASS | runtime-auth.txt |
| Resolución de dependencias instaladas | PASS, 53 compatibles | dependency-compatibility.txt |
| Trivy Bookworm / Trixie | FAIL, 55 / 44 entradas | trivy-bookworm.txt, trivy-trixie.txt |
| Trivy base adoptada / identidad | FAIL vulnerabilidades; PASS identidad | trivy-adopted-clean.txt y scanners/runtime-identity.json |
| Secretos y misconfiguración runtime en alcance Trivy | PASS, cero hallazgos HIGH/CRITICAL | scanners/trivy-runtime.json |
| Flutter analyze y tests checkout limpio | PASS, sin issues y 83 tests | clean-flutter-analyze.txt, clean-flutter-tests.txt |
| Licencias humanas, instalación SDK/NDK y APK debug | NOT RUN, esperando al usuario | comprobación de licencia ausente |
| Host Linux x86_64 en GitHub Actions, backend/Flutter/integración | PASS funcional; FAIL gate Trivy | runs 37856180080 y 37856180194, commit 5480688 |
| Android emulador/ADB/USB/sensor, Studio opcional | NOT RUN en esta fase | no se presume hardware ni LAN |

Los ensayos fallidos se conservan: fixture inicial de metadata con atributo incorrecto,
primera prueba Go con tmpfs no ejecutable y un comando runtime con flag de Compose
no soportado. Se corrigieron y sus repeticiones pasaron; no se cuentan esos intentos como PASS.
Los volúmenes, claves y recursos previos se preservaron. Solo se retiraron sondas propias
y usuarios sintéticos de los proyectos de prueba. El contenedor ajeno observado no se tocó.
La prueba runtime reutilizó la instancia propia retenida y un override temporal extra_hosts
solo para dirigir el alias api del driver al contenedor api-runtime en su misma red.
No hubo proxy, servicio adicional ni cambio de DNS/global del host.
Trivy filesystem también examinó el archivo Git de los archivos versionados antes del push:
PASS, cero hallazgos de secretos HIGH/CRITICAL; trivy-tracked-secrets.json conserva el resultado.

## GitHub Actions Linux

Los dos workflows se ejecutaron realmente sobre `5480688` en el PR Draft:

| Job | Estado | Evidencia remota |
|---|---|---|
| Backend tests, nativo | PASS, 133 | [CI](https://github.com/ferjovel06/agrifos/actions/runs/37856180080) |
| Flutter checks, nativo | PASS, analyze/tests | mismo run CI |
| Backend Docker, build/unit/infra | PASS: build, 133 backend y 37 infraestructura; job global FAIL por Trivy, config=0/image=1/identity=0 | [Docker environment](https://github.com/ferjovel06/agrifos/actions/runs/37856180194) |
| Supabase Auth, migraciones y persistencia | PASS, Linux Ubuntu 24.04 x86_64; bindings, JWT negativos, MFA, Alembic y reinicio reales | mismo run Docker |
| Flutter Linux amd64 Docker | PASS, 83 tests y locks conservados | mismo run Docker |
| Android CI | NOT RUN, licencia humana preservada | límite explícito del job Flutter |

Se descargaron los logs de jobs completados a ci-5480688-*.log en la evidencia privada.
La siguiente mejora conserva también un artifact `backend-scanner-summary` durante 30 días,
con CVEs/paquetes/versiones, contadores y digest, incluso ante FAIL. Omite matches de
secretos, Env, mensajes y cuerpos crudos; dos regresiones protegen esa selección y
evitan informar cero hallazgos cuando falta un reporte. Las pruebas locales pasan 39.
El paso Trivy y su fallo obligatorio permanecen intactos. El artifact usa upload-artifact
7.0.2 por commit oficial `cf430e030ddbb5b0abf93d22962f4752f3646cd9`.

## Comandos de uso

Desde la raíz del checkout que contiene estos commits, en Git Bash (Windows) o Bash
(Linux x86_64). Antes del merge, la rama de revisión es chore/docker-environment.

```bash
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

La preparación preserva env existentes. configure genera solo configuración local,
sin imprimir valores. Nunca copiar producción a .docker/local ni expandir config real
en logs. Para detener/reiniciar conservando volúmenes:

```bash
bash scripts/docker-dev.sh stop
bash scripts/supabase-local.sh stop
bash scripts/supabase-local.sh start
bash scripts/docker-dev.sh up
```

```bash
bash scripts/docker-dev.sh test
docker compose run --rm --no-deps -T backend-unit python -m unittest discover -s /checks/tests -v
bash scripts/check-docker.sh static
bash scripts/check-docker.sh images
bash scripts/test-docker-integration.sh
bash scripts/flutter-container.sh restore
bash scripts/flutter-container.sh analyze
bash scripts/flutter-container.sh test
```

images devuelve FAIL mientras existan HIGH/CRITICAL. El driver crea un proyecto nuevo,
prueba persistencia y conserva sus volúmenes; no necesita reset. Los puertos de test
54331–54334/8010 deben estar libres. La guía incluye comandos para revisar instancias retenidas.

**Intervención Android requerida**, personalmente en terminal interactiva:

```bash
bash scripts/flutter-container.sh licenses
```

Después de confirmar la revisión humana, continuar con:

```bash
bash scripts/flutter-container.sh sdk
bash scripts/flutter-container.sh apk
```

apk exige configuración pública local válida y exporta solo artifacts/agrifos-debug.apk,
ignorado por Git. No se modifica ni distribuye firma release.

## Archivos y commits nuevos

| Cambio | Archivos principales | Commit |
|---|---|---|
| Incorporar main sin reescribir historia | cambios originales de main y conflicto README | eaa146e |
| Corregir comparación/modelos de Alembic | backend/alembic/env.py, app/db/migration_scope.py, models/agronomic_reference.py, models/fertilization_engine.py, tests/test_migration_metadata.py | b789961 |
| Controles de privilegios | compose.yaml | 2a15ec7 |
| Integración JWT/metadata/listeners | compose.yaml, docker/integration.py, schema_check.py, audit_windows_listeners.ps1, scripts/test-docker-integration.sh | a22881a |
| Adoptar base Trixie | backend/Dockerfile, scripts/evaluate-trixie.sh, test-docker-integration.sh | 4474762 |
| Corregir prueba de identidad concurrente | scripts/check-docker.sh, docker/tests/test_scan_identity.py | 630fd8d |
| Guía, estados históricos, cierre y riesgos | README.md, docs/docker*.md | commit de documentación de esta entrega |
| Evidencia CI sanitizada y resultados Linux | .github/workflows/docker.yml, docker/scan_summary.py, tests/test_scan_summary.py, guía/informe | commit de evidencia CI de esta entrega |

Los 15 commits previos se preservan. Manifiestos/locks no se regeneraron en esta fase,
ni se reorganizaron backend/Flutter/tests. Los datos locales, herramientas descargadas,
credenciales, claves y artefactos generados están ignorados y no forman parte de la publicación.

## Entrega y bloqueantes

Se publicó chore/docker-environment y se abrió el PR #76 Draft hacia main; el árbol Git
quedó limpio tras los commits y el push. No hubo merge ni despliegue. Los fallos Trivy
permanecen visibles y los checks Linux funcionales se ejecutaron realmente.

Bloqueantes: ocho CVEs Debian sin corrección Trixie aceptada; revisión humana de Android
y APK pendiente. Linux funcional ya está comprobado mediante GitHub Actions;
el workflow global Docker permanece FAIL por seguridad. La credencial Git
existente tiene permiso push y se puede usar temporalmente con gh, sin imprimirla ni
guardar tokens en el checkout o cambiar la configuración global de autenticación.
