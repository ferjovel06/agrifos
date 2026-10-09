# Auditoría y refactorización offline-first

Base real: `8182f9f`. Inicio de la refactorización: `8ae4741`. La comparación
excluye tests, documentación, lockfiles y código ajeno al diff offline.

## Auditoría

| Componente | Líneas antes | Hallazgo | Acción |
|---|---:|---|---|
| Persistencia local | 512 | Búsquedas por ID cargaban y descifraban tablas completas; el motor recargaba también historial sincronizado | Consultas por clave primaria y filtro SQL de operaciones activas; esquema v1 intacto |
| Motor de sincronización | 968 | GET y POST duplicaban renovación de sesión | Una ruta de renovación; se conserva un solo vuelo, backoff, estados y cursores |
| Repositorios | 660 | Finca, parcela, alertas y fertilización repetían identidad, persistencia y comprobación de cambio de cuenta | Dos operaciones runtime explícitas para entidad y snapshot online |
| Gestión de estado | incluida arriba | Dos observadores de ciclo de vida controlaban sync y clima | `OfflineCoordinator` conserva la propiedad del ciclo de vida; la pantalla consulta ese estado |
| Clima | 718 | Flutter leía dos veces finca+caché; `WeatherService` tenía rutas paralelas para caché en memoria y persistente | Una lectura cliente y un único contrato `get_or_load`; producción inyecta PostgreSQL |
| Interfaz offline | 278 | Una subclase de repositorio existía solo para adaptar la edición de conflictos | Callback explícito de actualización; se elimina la clase adaptadora |

Se conservaron las abstracciones que protegen fronteras reales: `OfflineDatabase`
para transacciones/cifrado, `SyncEngine` para serializar ejecuciones y reintentos,
`OfflineRuntime` para concesión local y operaciones del dominio, y las dos cachés
meteorológicas PostgreSQL porque guardan representaciones diferentes (HTTP crudo
y pronóstico normalizado). Fusionarlas mezclaría políticas y formatos persistidos.

## Comparación medible

| Indicador | Antes (`8ae4741`) | Después | Diferencia |
|---|---:|---:|---:|
| Líneas productivas no vacías añadidas sobre la base | 2,929 | 2,883 | -46 (-1.6 %) |
| Clases/enums/mixins añadidos en el diff | 27 | 25 | -2 (-7.4 %) |
| Dependencias directas incorporadas | 7 | 7 | 0 |
| Ventanas duplicadas de seis líneas | 202 | 162 | -40 (-19.8 %) |
| SELECT SQLite, clima con caché fresca | 4 | 2 | -2 (-50 %) |
| SELECT SQLite, primer intento sin caché | 5 | 3 | -2 (-40 %) |
| Filas descifradas al buscar finca/parcela/muestra por ID | N de la tabla | 1 | acotado por PK |
| Operaciones descifradas al recargar estado | historial completo | solo no sincronizadas | acotado por estado |
| Llamadas Flutter → backend, 10 aperturas dentro de TTL | 1 | 1 | 0; la deduplicación se conserva |
| Llamadas backend → Open/MET, 10 servicios equivalentes | 1/1 | 1/1 | 0; la deduplicación se conserva |
| Ejecuciones efectivas ante llamadas sync simultáneas | 1 | 1 | 0; se conserva single-flight |
| Pruebas Flutter aprobadas | 116 | 117 | +1 |
| Pruebas backend aprobadas | 143 | 143 | 0 |

Las consultas SQLite se cuentan sobre el flujo determinista de clima: antes
`WeatherProvider` llamaba `cachedWeather` (finca+caché) y luego `weather`
(finca+caché, más intento si estaba vacío). Ahora `weather` es la única lectura y
consulta el registro de intento solamente cuando no existe pronóstico. El número
de statements de guardado/sync no cambia; se reduce el volumen leído y descifrado.

La duplicación usa ventanas exactas de seis líneas después de normalizar espacios,
en los archivos productivos modificados por offline. Es una señal reproducible,
no un análisis semántico. No se declara una mejora de memoria, batería o FPS:
no se ejecutó un perfilador en un teléfono físico.

## Compatibilidad y seguridad

- El esquema SQLite continúa en versión 1 y su DDL no cambió; archivos, entidades
  y operaciones creados por `8ae4741` se abren sin migración ni reconstrucción.
- No cambian la migración Alembic, contratos HTTP, estados de cola, UUID de
  idempotencia, revisiones, cursor, tombstones ni formato cifrado.
- Continúan las comprobaciones de cuenta después de cada espera remota. Las
  búsquedas puntuales incluyen `account` en la clave SQL.
- Siguen activas la verificación JWT ES256, issuer/audience/expiración, MFA,
  autorización por propietario y recibos transaccionales PostgreSQL.
- La clave de pronóstico persistente conserva `(latitud, longitud, días)`; la
  consolidación no invalida entradas meteorológicas ya almacenadas.

## Validación

Entorno local: Flutter 3.44.9/Dart 3.12.2 en contenedor de tooling, FastAPI en
Windows y PostgreSQL 17 aislado en loopback. Resultados:

- PASS: `flutter analyze`, cero problemas.
- PASS: 117 pruebas Flutter; una integración queda omitida en la suite genérica.
- PASS: 143 pruebas backend, incluidas siete con PostgreSQL real.
- PASS: driver Flutter SQLite → FastAPI HTTP → PostgreSQL: dos operaciones
  pendientes, respuesta perdida, un registro/un recibo y conflicto 55/77.
- PASS: head Alembic único `0f11a2b3c4d5`, upgrade y `compileall`.
- PASS: benchmark meteorológico posterior: 10 servicios, Open-Meteo 1 y MET 1.
- NOT RUN: Android/APK/Keystore/OTG, login/TOTP Supabase real, batería, memoria y
  reconstrucciones en dispositivo. No se aceptaron licencias Android.

`alembic check` conserva la divergencia heredada documentada en
[offline-validation.md](offline-validation.md); esta refactorización no altera
migraciones ni añade exclusiones.
