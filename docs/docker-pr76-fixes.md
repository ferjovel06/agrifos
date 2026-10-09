# PR #76: correcciones de conflictos, runtime y evidencia de seguridad

Fecha: 2026-10-08, Guatemala. Estado: bloqueado por seguridad y Android; PR Draft.
Los resultados remotos del HEAD definitivo se registran en el propio
[PR #76](https://github.com/ferjovel06/agrifos/pull/76), con enlaces a jobs y artifact.
Este documento registra las correcciones y pruebas locales anteriores al push final.

## Causas confirmadas y cambios

La ejecución Docker `37867130717`, intento 1, corresponde al HEAD `ea2874a`.
Su paso `Scan the built runtime and Docker configuration` falló con
configuration=0/image=1/identity=0 y 44 HIGH: hallazgos Debian, no fallo operativo.
Los otros cuatro jobs nativos/Docker pasaron. No se reutilizan para aprobar el HEAD nuevo.

Main avanzó a `8182f9f` incorporando el PR #80 (`f2269ef`). Solo añadió tres archivos
ya presentes en esta rama: Dockerfile, Compose y `.dockerignore`. El merge normal
`ee5fd7a` conservó la implementación aprobada, revisada semánticamente, e incorporó
las exclusiones `.uv-*/`, `.fastapicloud/` y `tools/`. API y pruebas de main quedan
cubiertas por los servicios existentes. Se preservaron pins, locks, migraciones,
preflight, loopback, privilegios restringidos y el entry point oficial de pruebas.

La imagen oficial Python 3.13/Trixie mantiene el mismo digest `bf44cdf…79c` y versión
3.13.16. APT actualizado en la base aislada confirmó Candidate=Installed en los 17
paquetes detectados antes del retiro; backports oficial contiene cero de esos paquetes.
El [registro de riesgos](docker-security-risk-register.md) conserva versiones,
fuentes oficiales, aplicabilidad, alternativas descartadas y cinco decisiones concretas.

`a684633` retira únicamente `mount` mediante APT del target runtime. La simulación
y construcción real eliminaron solo ese paquete; no hay autoremove, paquetes esenciales
forzados, bibliotecas sustituidas, inventario ocultado ni actualizaciones Python.
`mount`, `umount`, `losetup`, `swapon` y `swapoff` no se requieren en el backend/driver.
Las bibliotecas de Python permanecen, incluido curses, readline, SSL, SQLite y UUID.

`dc401a6` amplía el driver existente con la variante `runtime`. Ejecuta el servicio
`api-runtime` empaquetado sin binds de código, con las mismas garantías y pruebas reales.
CI usa esa variante y conserva el nombre del check. Se restringen destinos e inventarios
a los dos servicios previstos y al proyecto de prueba. La primera ejecución local falló
porque el auditor esperaba el nombre `api`; se corrigió, se añadió regresión y el siguiente
intento completó la integración. Ambos logs y los volúmenes quedaron conservados.

Se corrigió además la pérdida de evidencia ante JSON Trivy truncado y la ambigüedad
entre error operativo y hallazgos. Los archivos `scan_summary.py`, sus regresiones y
`check-docker.sh` producen `PASS`, `FAIL_FINDINGS`, `FAIL_OPERATIONAL` o `NOT_RUN`.
Los conteos ausentes/corruptos son null. Trivy devuelve 10 por hallazgos, 1 por error;
el gate devuelve 1 para ambos fallos. Cualquier incoherencia o identidad incompleta falla.
La DB se actualiza por el mecanismo normal y sus fechas se registran después del escaneo.
El resumen sanitizado se conserva aun con JSON corrupto; no publica Env, matches ni errores
crudos. No cambiaron el alcance HIGH/CRITICAL, los check names o branch protection.
Las tuberías unittest mantienen Bash pipefail; el escaneo no usa una tubería con tee.

Archivos modificados en esta fase:

| Cambio | Archivos |
|---|---|
| Merge y reducción runtime | backend/.dockerignore, backend/Dockerfile |
| Integración runtime y aislamiento | .github/workflows/docker.yml, scripts/test-docker-integration.sh, docker/audit_bindings.py, docker/configure.py, docker/integration.py, docker/tests/test_binding_audit.py, docker/tests/test_configure.py, docker/tests/test_integration_guard.py |
| Gate y evidencia | scripts/check-docker.sh, docker/scan_summary.py, docker/tests/test_scan_summary.py |
| Documentación | docs/docker.md, docs/docker-pr76-merge.md, docs/docker-security-risk-register.md, docs/docker-pr76-fixes.md |

## Resultados locales

| Validación | Resultado | Evidencia privada ignorada |
|---|---|---|
| Compose, Bash y Hadolint | PASS; advertencias existentes visibles | pr76-current-static-final.log |
| Backend Windows y Docker | PASS, 156 pruebas en cada uno | pr76-current-backend.log; pr76-current-backend-docker.log |
| Construcción desde archivos versionados sin env/venv del host | PASS | pr76-close/clean-build.log |
| Backend desde copia limpia | PASS, 156 pruebas | pr76-close/clean-backend.log |
| Infraestructura desde copia limpia | PASS, 56 pruebas (antes 39; 17 regresiones nuevas) | pr76-close/clean-infrastructure.log |
| Imports, UID 10001, CapBnd/CapEff=0 y NNP=1 | PASS, misma imagen final escaneada y probada | pr76-close/final-runtime-probe.json |
| Auth/MFA/JWT, PostgreSQL, Alembic y persistencia con API runtime | PASS, proyecto agrifos-it-5f94a330 | pr76-current-runtime-integration-fixed.log |
| Driver runtime desde copia limpia | PASS, proyecto agrifos-it-4446705c; bootstrap CLI verificado | pr76-close/clean-runtime-integration.log |
| Flutter analyze / tests | PASS, sin incidencias / 83 pruebas | pr76-current-flutter-analyze.log; pr76-current-flutter-test.log |
| Trivy runtime final | FAIL_FINDINGS, 40 HIGH / 0 CRITICAL / ocho CVE | scanners/gate-summary.json; pr76-close/final-clean-runtime-scan.log |
| Android SDK/APK | NOT RUN; licencias y paquetes SDK ausentes, ningún APK | inspección de volúmenes e imagen Android |

La copia limpia procede del árbol Git `9fcf80386fdeb12d148478939a67fe3fdce5d239`,
con los cambios de código definitivos. Los documentos agregados después no alteran
el contexto backend ni el código verificado. No disminuyeron pruebas ni aparecieron skips.
La integración verifica health/db 200, head Alembic `b2c4d6e8f901`, ausencia de drift,
login ES256 real, issuer/audience/expiración, rechazo HS256 y firma/token/password inválidos,
MFA AAL1/AAL2 y persistencia. Los rechazos de redirecciones JWKS se conservan en las pruebas
de autenticación HTTP. Docker y Windows confirman cuatro bindings/listeners 127.0.0.1 antes
y después del reinicio. No hay integración sustituida por mocks.

## Imagen y escaneo medidos

Base: `python:3.13.16-slim-trixie@sha256:bf44cdfcb76cd3b41e879bc058fc37ec5872002ccfde7fcb765e218cde0cd79c`.
Runtime inspeccionado: `sha256:a12fea3cab291d950186e21ca5443b027ea897fa41d9886ef962484074e28773`.
Config exportado/Trivy: `sha256:d13eb9cce92f5c64c78122b8a5c72fbf64149e218ea96dd451d7b15aa0408335`.
La prueba relaciona el ID inmutable inspeccionado con el config del archivo exportado
y con ImageID de Trivy. Plataforma linux/amd64; Debian 13.7/Trixie; Trivy 0.75.0 fijado
por digest. DB esquema 2: UpdatedAt `2026-10-08T15:33:46.578791096Z`,
NextUpdate `2026-10-09T15:33:46.578790805Z`, DownloadedAt `2026-10-08T16:34:48.095634265Z`.
La DB estaba vigente y su comprobación/actualización normal terminó con código 0.

Comando oficial: `bash scripts/check-docker.sh images`. Config=0, image=10, identity=0,
database=0, metadata=0; gate exit 1, sin errores operativos. Secretos y misconfiguraciones
HIGH/CRITICAL reportados: cero. Antes 44 HIGH; después 40 HIGH en 16 paquetes y ocho CVE.
Se eliminaron cuatro detecciones de mount; ningún CVE completo quedó corregido.
Todos los FixedVersion Trixie restantes están vacíos. No se aplicó VEX ni excepción.
Una reconstrucción de la copia limpia cambió el config digest respecto del primer
escaneo. La verificación lo detectó; se conservó ese resultado y se repitió el
escaneo sobre el runtime final. Los builds CI generan y verifican sus propios identificadores; no se presume igualdad
binaria de imágenes construidas en equipos distintos.

## Uso y decisiones pendientes

```bash
bash scripts/check-docker.sh static
docker compose build backend-unit migrate
docker compose run --rm --no-deps -T backend-unit
docker compose run --rm --no-deps -T backend-unit python -m unittest discover -s /checks/tests -v
AGRIFOS_INTEGRATION_VARIANT=runtime bash scripts/test-docker-integration.sh
bash scripts/check-docker.sh images
bash scripts/flutter-container.sh analyze
bash scripts/flutter-container.sh test
```

Para Android, el usuario debe ejecutar personalmente en Git Bash
`bash scripts/flutter-container.sh licenses`. Tras completar esa aceptación interactiva,
los comandos documentados son `sdk` y `apk`. No se aceptaron términos automáticamente.

Las cinco decisiones U/N/S/A/P del registro identifican CVEs, paquetes, fixes externos,
alcance de imagen, evidencia, mitigaciones, responsable propuesto y vencimiento 2026-11-07.
U/N/A conservan el bloqueo hasta disponer de revisiones compatibles o una aprobación
específica de riesgo; S/P requieren revisión humana de las pruebas de componente ausente
antes de cualquier VEX/excepción. CVE-2026-78409 sigue indeterminado. No se declara
terminada la dockerización ni se recomienda integrar con este gate fallido.

Se publica solamente chore/docker-environment, preservando commits mediante merges normales.
Main local y chore/backend-audit mantienen `a1df7e0`; no hay force push, PR nuevo, merge ni
despliegue. Los recursos ajenos y los volúmenes preexistentes se conservan.
