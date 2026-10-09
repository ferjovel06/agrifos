# Validación offline-first y clima

Entrega en `feat/offline-first-foundation`, aislada desde `origin/main` **8182f9f**.
Estado: implementación y aceptación automatizada local disponibles para Draft PR;
no fusionada, desplegada ni certificada en un dispositivo Android.
Arquitectura/uso: [offline-first.md](offline-first.md). Auditoría del estado previo:
[offline-audit.md](offline-audit.md). Resultados y hashes: [offline-evidence.json](offline-evidence.json).

## Resultados antes/después

| Elemento | Antes | Después | Evidencia |
|---|---|---|---|
| Lectura offline | Repositorios dependían de HTTP; listas en memoria | SQLite cifrado por cuenta para datos descargados; snapshots auxiliares | PASS: cierre/reapertura de archivo SQLite y driver real A |
| Escritura offline | Guardado remoto; sin outbox persistente | Commit SQLite atómico de entidad + operación UUID; lecturas y laboratorio | PASS B: proceso Dart termina con exit 70 sin cerrar DB; otro proceso recupera guardado |
| Sincronización | Sin protocolo durable bidireccional | Cola persistente, revisiones, feed paginado, tombstones, reintentos y revisión | PASS C: dos pendientes antes de cierre, reconexión real Flutter→HTTP→PostgreSQL |
| Duplicados | Sin recibo durable por operación | Recibo/hash por usuario+UUID, commit junto a mutación | PASS D: respuesta descartada después de commit; un registro y un recibo; cuatro entregas concurrentes |
| Conflictos | Sin candidato local durable | 409 con versión remota; conserva candidatos, no sobrescribe automáticamente | PASS E real: N local=55, servidor=77; revisión conserva historial |
| Clima Flutter → Backend | 10 consultas para 10 aperturas equivalentes | 1 consulta dentro del TTL de 15 minutos; 0 offline | PASS: benchmark HTTP sintético y tests de reloj/concurrencia |
| Clima Backend → Proveedor | 10 Open + 10 MET en diez servicios independientes | 1 Open + 1 MET para el mismo escenario; diez requests entrantes | PASS: HTTP sintético, adaptadores reales y caché PostgreSQL compartida |
| Seguridad | JWT/MFA/roles en backend; sesión local existente | Mantiene controles remotos; payload AES-GCM, claves de caché HMAC, grants 72h y namespace por entorno | PASS F: aislamiento, cambio de cuenta durante POST, grants expirados/rollback/logout; JWT ES256 real |

Los escenarios meteorológicos son mediciones controladas, **no tráfico de
producción ni una promesa de reducción universal**. El escenario de proveedor
usa primario 503 y fallback fresco para diez ubicaciones equivalentes entre
instancias independientes. Flutter y backend son capas distintas.

## Matriz de pruebas

| Comprobación | Estado | Resultado y alcance |
|---|---|---|
| Backend original | PASS | 136 tests de la base |
| Backend actual completo | PASS | 143 tests, incluidos siete con PostgreSQL real |
| Flutter original | PASS | 83 tests |
| Flutter actual completo | PASS | 116 tests; el test HTTP queda SKIP/NOT RUN en ejecución genérica y se ejecutó aparte |
| Flutter analyze | PASS | Cero problemas |
| A/B lectura/reinicio/escritura | PASS | SQLite real en archivo; cierre normal y terminación abrupta de proceso Dart |
| C/D/E integración de tres capas | PASS | Flutter nativo Linux en contenedor, FastAPI HTTP real Windows, PostgreSQL Linux aislado; dos pendientes, pérdida de respuesta, replay y conflicto |
| F aislamiento | PASS | Datos/ops/caché por cuenta, AAD rechaza ciphertext de otro usuario, respuestas tardías no restauran sesión ni lista |
| Autorización remota | PASS | Firma ES256 con JWKS HTTP controlado real; issuer/aud/exp inválidos rechazados; factor MFA verificado en PG: aal1 403 y aal2 autorizado |
| G reutilización clima | PASS | TTL cliente 15m, diez clientes de caché independientes con un upstream; Expires mayor que TTL respetado |
| H proveedor caído | PASS | 429 Retry-After, 304/If-Modified-Since exacto, fallback, stale/histórico, cooldown durable, ningún nuevo alerta basado en histórico |
| Proveedores públicos en vivo | PASS | Una llamada HTTP 200 a cada proveedor, coordenadas públicas de Ciudad de Guatemala; respuestas normalizadas posteriormente desde caché |
| Migración upgrade / head único | PASS | Migración aditiva aplicada; head `0f11a2b3c4d5`; compileall pasa |
| Alembic check | FAIL | Diferencias heredadas reproducidas también en el esquema original; detalles abajo |
| Secret scan Trivy 0.75.0 | PASS | Cero hallazgos en snapshot tracked; no escaneo de CVEs ni exclusiones añadidas |
| Build web en raíz del proyecto | FAIL | No hay scaffold web versionado en la base |
| Compilación web aislada | PASS | Copia de código/lock y scaffold temporal; JS y wasm dry-run compilan; no demuestra funcionamiento en navegador |
| Android/APK/Keystore/OTG/dispositivo | NOT RUN | No se aceptaron licencias; requiere aceptación y pruebas físicas del usuario |
| Supabase Auth en vivo | NOT RUN | No se efectuaron login/refresh/TOTP contra un proyecto real; fixture JWT/MFA no sustituye esa prueba |
| Arranque nativo iOS/macOS/Windows/Linux | NOT RUN | Tests Dart/SQLite Linux no certifican plugins nativos ni empaquetado de esas plataformas |
| Cuotas/batería/tráfico de producción | NOT RUN | No se hicieron benchmarks productivos ni activación comercial |

En la primera instrumentación del smoke público el script consultaba un campo
`provider` ausente en el payload Open-Meteo: registró un fallo del instrumento
tras HTTP 200. Se corrigió el verificador y validó el mismo payload conservado en
PG; la segunda ejecución no hizo llamadas adicionales. Se conservan ambos logs.
Fallos de desarrollo anteriores permanecen en `tmp/offline`; se distinguen de
los resultados finales de la matriz.

## Alembic: divergencia heredada

`alembic check` detecta `auth.users` como tabla externa ausente del esquema
comparado, el índice `ix_agronomic_reference_sets_active` y diferencias de
`ondelete=RESTRICT` en FK de `optimal_requirements` y `stage_factors`. Se creó una
segunda base **aislada** y se aplicaron las migraciones originales extraídas de
8182f9f: aparecen las mismas categorías. No aparecen diferencias nuevas en las
cuatro tablas offline/clima ni en sus columnas de revisión. No se modificaron
migraciones antiguas, filtros de autogenerate ni reglas de seguridad para ocultarlo.
Debe corregirse mediante una tarea independiente antes de tratar `check` como
un gate limpio. La migración nueva sí se aplica y los tests reales pasan.

## Comandos reproducibles

Configuración de uso: `.env` del README, PostgreSQL/Supabase propios de desarrollo,
`uv sync --project backend --locked`, migración **desde backend** mediante el bloque siguiente, y `flutter pub get --enforce-lockfile`
en `app_flutter`. Nunca se requiere reset de una base existente.

```powershell
# Desde backend, con DATABASE_URL de desarrollo y SUPABASE_URL configurados:
uv sync --locked
uv run alembic upgrade head
uv run alembic heads
uv run python -m compileall -q app alembic/versions
uv run python -m unittest discover -s tests
# Desde app_flutter:
flutter pub get --enforce-lockfile
flutter analyze
flutter test
flutter run
```

Las siete pruebas PostgreSQL y el driver requieren una base exclusivamente de
fixture, llamada `agrifos_offline_*`, en loopback. Crea una nueva base o contenedor
propio; no apuntes a datos reales. Las credenciales de este ejemplo son locales,
de prueba. Cada ejecución genera UUID nuevos y no borra datos existentes.

```powershell
# Ejemplo opcional de un contenedor NUEVO dedicado, con puerto libre:
docker run -d --name agrifos-offline-example -p 127.0.0.1:64288:5432 `
  -e POSTGRES_PASSWORD=offline_isolated_fixture `
  -e POSTGRES_DB=agrifos_offline_example postgres:17-alpine
$env:OFFLINE_TEST_DATABASE_URL='postgresql+asyncpg://postgres:offline_isolated_fixture@127.0.0.1:64288/agrifos_offline_example'
$env:DATABASE_URL=$env:OFFLINE_TEST_DATABASE_URL
$env:SUPABASE_URL='http://127.0.0.1:59998'
# Desde backend:
uv run python -m unittest tests.test_offline_postgres
# Desde raíz, con Flutter en PATH:
uv run --project backend python scripts/offline_integration.py
uv run --project backend python scripts/weather_call_benchmark.py --persistent
# Con tooling Flutter ya disponible en contenedor, como la validación local:
uv run --project backend python scripts/offline_integration.py `
  --docker-tool-container agrifos-offline-tools-01 --client-host host.docker.internal
```

La fixture Auth crea esquema/usuarios/factores de prueba y emite JWT ES256
verificados mediante JWKS real en loopback. Su archivo temporal con token queda
en `.dart_tool`, se elimina al terminar y jamás se sube como artifact. Los artifacts
CI son únicamente logs sanitizados y `real-integration.json`. Los logs locales
están ignorados; el JSON versionado conserva hashes y resultados, no secretos.

## Compatibilidad y limitaciones

- Lock Flutter: **cero versiones existentes cambiadas**, 14 paquetes nuevos;
  path_provider/uuid/url_launcher existentes pasan a directos. Lock Python intacto.
  Connectivity 7.3.1 conserva el constraint dbus/geolocator existente. Toolchain sin actualización.
- La interfaz nativa usa SQLite y almacén seguro; web conserva el flujo online.
  La compilación web se hizo en scaffold temporal porque el proyecto no lo versiona.
- Grant offline de 72h desde perfil backend verificado; no hay primer login offline.
  No se conoce una revocación remota durante desconexión. Logout conserva cola
  cifrada y requiere nuevo acceso online. Metadatos UUID/tiempos/estados son legibles.
- Finanzas, perfil/MFA, metadatos de finca/parcela, borrados y nuevos cálculos
  siguen online. Cálculo no utiliza muestras pendientes como entradas confirmadas.
- Catálogos y resultados auxiliares son snapshots; no se incluyeron en el feed.
- Journal global serializa escrituras para preservar orden de commit/cursor;
  reduce concurrencia. No hay compacción/retención del journal/recibos todavía.
  Cursors expiran a 30 días y se puede repetir descarga sin borrar operaciones.
- El cache meteorológico por clave no limita la cuota agregada de ubicaciones
  diferentes. Debe evaluarse antes de tráfico alto. Open-Meteo gratuito es no
  comercial; no se activó pago y se preserva atribución CC BY 4.0 en la tarjeta.
- No se aplicaron estos cambios a Docker. La rama original se verificó limpia en
  `46f7003c53afc5b510baaef98ae12c9d3914b530`, `chore/docker-environment`.
  PR #76 permanece fuera de esta entrega. No hubo merge/deploy/reset de volúmenes.

## Git, CI y entrega

Rama de destino de revisión: `main`; se autoriza publicar solamente esta nueva
rama y un **Draft PR**. El resultado remoto de CI se incorporará tras crearlo.
Los workflows originales se conservan; se añade la aceptación real en Ubuntu
con PostgreSQL 17 y Flutter 3.44.9. No se editaron workflows Docker.

Commits de implementación antes del cierre documental:

```text
7db000e docs(offline): audit existing field workflows and weather requests
4b10d0a feat(sync): persist owner-scoped operations and incremental changes
eb05a2f feat(weather): share durable provider caches across workers
5d9c8ee feat(storage): encrypt durable account-scoped SQLite data
cc54b1a feat(offline): queue field writes and synchronize stable operations
a70926f feat(ui): expose offline status and conflict review in field workflows
66b1035 test(offline): exercise SQLite HTTP and PostgreSQL acceptance in CI
f2ea058 fix(offline): guard late responses and require confirmed agronomic inputs
0334a70 fix(weather): expose provider and license attribution
fbf4bbf fix(storage): isolate secure grants and keys by backend environment
e283dca fix(storage): conceal private query coordinates in cache keys
9738fbe test(sync): reconnect multiple persisted operations over real HTTP
```

## Archivos modificados

Listado contra la base auditada (incluye implementación, pruebas y documentación):

```text
.github/workflows/offline-integration.yml
README.md
app_flutter/android/app/src/main/AndroidManifest.xml
app_flutter/lib/core/network_health.dart
app_flutter/lib/data/api/alerts_repository.dart
app_flutter/lib/data/api/api_client.dart
app_flutter/lib/data/api/farm_repository.dart
app_flutter/lib/data/api/fertilization_repository.dart
app_flutter/lib/data/api/lab_analysis_repository.dart
app_flutter/lib/data/api/parcel_repository.dart
app_flutter/lib/data/api/readings_repository.dart
app_flutter/lib/data/api/weather_repository.dart
app_flutter/lib/data/local/offline_database.dart
app_flutter/lib/data/local/offline_executor.dart
app_flutter/lib/data/local/offline_executor_native.dart
app_flutter/lib/data/local/offline_executor_stub.dart
app_flutter/lib/data/local/secure_vault.dart
app_flutter/lib/data/sync/offline_runtime.dart
app_flutter/lib/data/sync/sync_engine.dart
app_flutter/lib/domain/entities/lab_analysis.dart
app_flutter/lib/domain/entities/reading.dart
app_flutter/lib/domain/entities/weather_forecast.dart
app_flutter/lib/main.dart
app_flutter/lib/presentation/auth/auth_gate.dart
app_flutter/lib/presentation/auth/auth_provider.dart
app_flutter/lib/presentation/farm/farm_provider.dart
app_flutter/lib/presentation/farm/parcel_provider.dart
app_flutter/lib/presentation/home/home_screen.dart
app_flutter/lib/presentation/home/latest_reading_provider.dart
app_flutter/lib/presentation/home/weather_provider.dart
app_flutter/lib/presentation/home/widgets/weather_conditions_card.dart
app_flutter/lib/presentation/lab_analysis/lab_analysis_screen.dart
app_flutter/lib/presentation/navigation/main_shell.dart
app_flutter/lib/presentation/navigation/offline_coordinator.dart
app_flutter/lib/presentation/navigation/sync_review_screen.dart
app_flutter/lib/presentation/navigation/sync_status_bar.dart
app_flutter/lib/presentation/planification/planification_screen.dart
app_flutter/lib/presentation/sensor/sensor_provider.dart
app_flutter/lib/presentation/sensor/widgets/telemetry_card.dart
app_flutter/pubspec.lock
app_flutter/pubspec.yaml
app_flutter/test/data/offline_database_test.dart
app_flutter/test/data/offline_weather_auth_test.dart
app_flutter/test/data/sync_engine_test.dart
app_flutter/test/integration/offline_http_test.dart
app_flutter/test/presentation/farm/farm_provider_test.dart
app_flutter/test/presentation/home/widgets/weather_conditions_card_test.dart
app_flutter/test/support/offline_crash_writer.dart
app_flutter/test/support/offline_fixture.dart
backend/alembic/versions/0f11a2b3c4d5_add_offline_sync_and_weather_cache.py
backend/app/dependencies/weather.py
backend/app/integrations/weather_http.py
backend/app/integrations/weather_provider.py
backend/app/main.py
backend/app/models/__init__.py
backend/app/models/farm.py
backend/app/models/mixins.py
backend/app/models/offline.py
backend/app/models/soil.py
backend/app/routers/alerts.py
backend/app/routers/offline.py
backend/app/routers/weather.py
backend/app/schemas/farm.py
backend/app/schemas/lab_analysis.py
backend/app/schemas/offline.py
backend/app/schemas/parcel.py
backend/app/schemas/reading.py
backend/app/schemas/weather.py
backend/app/services/climate_alert_service.py
backend/app/services/weather_http_cache.py
backend/app/services/weather_service.py
backend/tests/test_offline_postgres.py
backend/tests/test_weather.py
docs/ESTADO_IMPLEMENTADO.md
docs/README.md
docs/diagrams/architecture_diagram.mmd
docs/diagrams/class_diagram.mmd
docs/diagrams/er_diagrams/agrifos_er_diagram.mmd
docs/diagrams/er_diagrams/er_climate_alerts.mmd
docs/diagrams/er_diagrams/er_core_farm.mmd
docs/diagrams/er_diagrams/er_fertilization_plans.mmd
docs/diagrams/er_diagrams/er_finance.mmd
docs/diagrams/er_diagrams/er_phenology.mmd
docs/diagrams/er_diagrams/er_soil_data.mmd
docs/offline-audit.md
docs/offline-evidence.json
docs/offline-first.md
docs/offline-validation.md
scripts/offline_integration.py
scripts/weather_call_benchmark.py
```
