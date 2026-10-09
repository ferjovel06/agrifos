# PR #76: conflicto con main y validación de seguridad

Fecha: 2026-10-08, Guatemala. PR existente: [#76](https://github.com/ferjovel06/agrifos/pull/76).
Rama: `chore/docker-environment`. **Draft; no se recomienda merge mientras el gate de seguridad siga en FAIL.**
La aceptación humana de Android y el APK siguen pendientes; esta fase no los ejecuta.
Main avanzó nuevamente durante esta tarea. El resultado más reciente es la incorporación
de `3583b7d` y **156 pruebas backend PASS**, documentada en la actualización al final.
Los resultados 151 de la primera resolución se conservan como evidencia de esa etapa.

## Causa del conflicto y resolución

Se verificó un árbol limpio en `3995d11`, antes de editar. Fetch encontró dos commits
nuevos en main: `26504fd`, refactorización meteorológica, y su merge `325f1fb` del PR #77.
El ancestro común era `33e53a3`. Las ramas locales main y chore/backend-audit permanecieron
en `a1df7e0`; se trabajó exclusivamente en la rama del PR.

El merge normal de origin/main produjo un único conflicto, en backend/app/core/config.py:
ambas ramas insertaron campos inmediatamente después de SUPABASE_URL.
Main no eliminó intencionadamente JWKS; ese campo no existía en el ancestro común.

| Procedencia | Cambio | Resolución |
|---|---|---|
| Docker | SUPABASE_JWKS_URL opcional y propiedad supabase_jwks_url | Conservados, incluidos fallback público y normalización de barra final |
| Main | Import Field y WEATHER_TIMEOUT_SECONDS=15.0, WEATHER_CONNECT_TIMEOUT_SECONDS=5.0, WEATHER_REQUEST_ATTEMPTS=2, WEATHER_FALLBACK_REQUEST_ATTEMPTS=1 | Conservados, incluidos límites gt=0 y ge=1 |

La fábrica meteorológica nueva utiliza los cuatro campos. Auth obtiene las claves por
supabase_jwks_url y sigue derivando el issuer de la URL pública SUPABASE_URL.
No se cambió auth.py, ES256, firma, audience, issuer, expiración ni MFA.
No se añadió SUPABASE_JWT_ISSUER ni se cambiaron dependencias, locks o migraciones.
Los demás archivos entrantes del PR #77 se conservaron con el merge automático.

Se añadieron tres regresiones a backend/tests/test_auth_config.py: defaults JWKS/clima,
coexistencia de overrides con issuer público, y rechazo de cero/negativos en los cuatro
ajustes meteorológicos. Aíslan os.environ y dotenv y conservan las pruebas previas.

El merge se confirmó en `39374598ad39e9cc67e3874f7d986305d7fe3f73`, con padres
`3995d11` y `325f1fb`. No hubo rebase, force push, reset ni pérdida de commits.

## Validación local antes de confirmar el merge

| Comprobación | Resultado real | Evidencia privada ignorada |
|---|---|---|
| Conflictos, marcadores, sintaxis y diff whitespace | PASS | índice resuelto, ast.parse y git diff --check |
| Entry point backend nativo con lock congelado | PASS, 151 pruebas | .docker/evidence/pr76-merge/backend-native.log |
| Construcción backend test/runtime y development por driver | PASS | backend-build.log e integration.log |
| Backend completo en Docker | PASS, 151 pruebas | backend-docker.log |
| Infraestructura | PASS, 39 pruebas | infrastructure.log |
| Compose quiet, Bash y Hadolint | PASS en errores; advertencias APT/SHELL existentes permanecen visibles | static.log |
| Integración real Supabase/PostgreSQL/FastAPI | PASS | integration.log, proyecto nuevo agrifos-it-6fcefeca |
| ES256, firma/issuer/aud/exp inválidos, MFA y persistencia | PASS | mismo driver; JWT firmados reales y TOTP real |
| Alembic antes/después de reinicio y detección read-only de drift | PASS; head b2c4d6e8f901 | mismo driver |
| Cuatro bindings Docker y listeners Windows | PASS, 127.0.0.1 antes/después del reinicio | bindings y windows-listeners en .docker/integration/agrifos-it-6fcefeca |
| UID/capabilities/no-new-privileges | PASS | API real y security/runtime-applicability.txt |
| Escaneo de secretos del árbol staged exacto | PASS, cero hallazgos | tracked-secrets-44809fd6b2f7.json |
| Trivy de imagen y configuración | FAIL: 44 HIGH, 0 CRITICAL; config=0/image=1/identity=0 | trivy.log y public-scanner-summary.json |
| Android licencias/SDK/APK/hardware | NOT RUN, intervención humana pendiente | control preservado |

Las 151 pruebas son las 133 anteriores, 15 nuevas procedentes de main y tres regresiones
de esta resolución. La integración no sustituye Auth/PostgreSQL/MFA por mocks.
El runtime escaneado contiene la resolución; su digest de configuración es
`sha256:aed415eb94a1bd92c3544e07c71f69d16d12eb39e33b448e1358d9348e4e4cc0`.
La prueba de identidad confirmó la coincidencia con el archivo exportado, aunque el
driver reconstruyó el tag simultáneamente. Secretos y misconfiguraciones HIGH/CRITICAL
del runtime/configuración reportaron cero en el alcance configurado.
Se detuvieron solo los recursos del proyecto nuevo; sus volúmenes y claves se conservaron.

## Check fallido y correcciones disponibles

Se inspeccionaron los logs reales del [run anterior 37856890815](https://github.com/ferjovel06/agrifos/actions/runs/37856890815),
HEAD 3995d11. Falló únicamente el paso `Scan the built runtime and Docker configuration`.
Build, backend133, infraestructura39, configuración e identidad pasaron. El escáner produjo
un informe válido con ocho CVEs distintos y 44 entradas HIGH; no fue un error de build o tests.
El escaneo local nuevo después de resolver el conflicto reproduce ese resultado.

La consulta APT actualizada y aislada del 2026-10-09T00:30Z confirmó que los 17 paquetes
afectados tienen Candidate=Installed desde Trixie/security/updates. El índice oficial
Trixie backports amd64 no contiene ninguno de ellos. No se instalaron paquetes ni se
modificaron fuentes APT del host o del Dockerfile.

El [registro por CVE](docker-security-risk-register.md) conserva versiones, paquetes,
fuentes oficiales, aplicabilidad y mitigaciones. No existe hoy un parche mínimo
disponible desde esos repositorios que elimine los ocho avisos. Upstream util-linux
publicó 2.41.6, pero no es un paquete Debian Trixie/backport compatible listo para usar.
Sid, paquetes esenciales propios o una imagen distroless/Alpine requieren otra evaluación.
No se aplicaron esas alternativas ni excepciones Trivy.

## Publicación y comprobación de CI

Se publica la misma rama para actualizar el PR #76; no se abre otro PR ni se fusiona main.
Los resultados posteriores al push, sus HEAD SHA y enlaces a los cinco jobs se conservan
en la descripción del PR existente. Para auditar una revisión concreta, comprobar el
head_sha del run y los logs de cada paso; no reutilizar el resultado histórico 3995d11
como prueba de un HEAD nuevo. La evidencia privada se conserva en .docker/evidence/pr76-merge/.
El artifact backend-scanner-summary omite credenciales, matches de secretos y Env crudos.

Comandos oficiales utilizados desde la raíz, en Git Bash/Bash:

```bash
bash scripts/test-backend.sh
docker compose build backend-unit migrate
docker compose run --rm --no-deps -T backend-unit
docker compose run --rm --no-deps -T backend-unit python -m unittest discover -s /checks/tests -v
bash scripts/check-docker.sh static
bash scripts/check-docker.sh images
bash scripts/test-docker-integration.sh
```

images sigue devolviendo error por los HIGH. No cambió ningún workflow ni criterio de
seguridad en esta fase. Recomendación: conservar el Draft/gate y esperar correcciones
Trixie compatibles. Cualquier excepción específica requiere una decisión humana previa,
con CVE, paquetes/digest, alcance, controles, responsable, vencimiento y retirada.

## Actualización por nuevos cambios de main durante la validación

Después del primer push, el remoto main avanzó a `3583b7d`: PR #78 de caché
meteorológica (`6462ad8`/`769ec71`) y PR #79 de artefactos de desarrollo
(`a95e365`, `b558c82`, `d47d3f4`/`3583b7d`). GitHub aún mostraba dirty y no ejecutó
workflows nuevos sobre b55642e. Se inspeccionó/fusionó ese estado mediante otro merge
normal, sin reescribir la primera resolución.

El único conflicto nuevo fue .gitignore, por dos bloques añadidos al final del archivo.
Se conservó su unión: .docker/, .tools/, artifacts/, supabase/.local/ y bytecode Docker,
además de /backend/tools/, /app_flutter/tool/ y /app_flutter/web/ de main. git check-ignore
comprobó ambos grupos; ninguno de los archivos privados de esos directorios está staged.
Las eliminaciones de demos/notas y sus referencias son cambios ya publicados en main,
incorporados sin borrar archivos personales, datos o historia Git.

config.py se fusionó automáticamente conservando JWKS y los siete ajustes meteorológicos.
Los tres nuevos son WEATHER_CACHE_FRESH_SECONDS=1800, WEATHER_CACHE_STALE_SECONDS=21600
y WEATHER_CACHE_RETRY_SECONDS=60, con gt=0. Las tres regresiones se ampliaron a todos los
campos; los overrides positivos respetan stale >= fresh, exigido por la caché de main.
Se conservó la caché compartida por proceso y sus cinco pruebas nuevas.

El segundo merge es `06cae7e886dc74f2690188e4883b302c23eae230`, padres b55642e y 3583b7d.
git merge-tree origin/main HEAD devolvió exactamente el árbol HEAD, sin conflictos.
Ambos main incorporados y el HEAD Docker original 3995d11 siguen siendo ancestros.

| Revalidación de main 3583b7d | Resultado real | Evidencia privada |
|---|---|---|
| Backend Windows y Docker | PASS, 156 pruebas en cada uno | backend-native-main3583.log y backend-docker-main3583.log |
| Infraestructura y validación estática | PASS, 39 pruebas; sin errores Hadolint | infrastructure-main3583.log y static-main3583.log |
| Integración real y persistencia completa | PASS, proyecto nuevo agrifos-it-e941513d | integration-main3583.log; volúmenes conservados |
| Auth/JWT/MFA, Alembic y loopback Windows antes/después | PASS | mismo driver |
| Árbol staged sin secretos | PASS, cero hallazgos | tracked-secrets-283eb0825348.json |
| Trivy del runtime nuevo | FAIL, 44 HIGH/0 CRITICAL; config=0/image=1/identity=0 | trivy-main3583.log y public-scanner-summary-main3583.json |

Las 156 pruebas son 133 originales, 20 meteorológicas incorporadas de main y tres de
configuración nuevas. El digest de configuración del runtime nuevo es
`sha256:e59b4dc689d7b26c52b889e2c9f4c5bde550afa04a7a265a345116e41e4e8ef6`,
verificado contra el archivo escaneado. Los ocho CVE/paquetes/versiones no cambiaron;
los secretos y misconfiguraciones HIGH/CRITICAL reportados siguen en cero.
No cambió auth.py, ningún lockfile, migración histórica, workflow o política Trivy.
Los resultados de los cinco jobs para el HEAD publicado definitivo se registran en el PR #76.
