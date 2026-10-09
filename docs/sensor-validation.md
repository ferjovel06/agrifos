# Informe de adquisición, calidad y calibración NPK

Fecha: 9 de octubre de 2026. Rama `feat/npk-measurement-reliability`, basada en
`532ad74c919bc0b620b4b20f1d0d7e568a8d20b6` del PR #82, que permanece abierto.
Se implementó y probó la parte verificable mediante software. **No se acredita
compatibilidad física ni exactitud analítica de la sonda.**

## 1. Estado de la conexión física

| Elemento | Estado | Evidencia |
|---|---|---|
| Modelo identificado | NOT RUN | No se recibió fabricante, modelo, serie ni manual |
| USB-C/OTG | NOT RUN | No hay teléfono/adaptador identificados ni ensayo físico |
| Alimentación | NOT RUN | Tensión, corriente e interfaz eléctrica desconocidas |
| Protocolo | NOT RUN | El mapa heredado carece de respaldo; no se habilita por defecto |
| Tramas auténticas | NOT RUN | Ningún archivo capturado del dispositivo real |
| Lectura Android real | NOT RUN | Sin dispositivo, permisos ni conexión física probados |

La [auditoría inicial](sensor-audit.md) identifica un controlador USB existente,
no un simulador de producción, pero con selección automática y supuestos sin
verificar. Se eliminó la selección del primer dispositivo y el filtro VID/PID
supuesto. No se enviaron comandos al hardware, sondeos eléctricos ni escrituras
de registros. El transporte queda condicionado a un perfil documentado,
verificado y seleccionado explícitamente. Las fixtures Modbus son sintéticas.

## 2. Calidad y calibración

Resultados **reales**, exclusivamente:

| Parámetro | Valor crudo | Filtrado | Calibrado | Error frente a laboratorio |
|---|---|---|---|---|
| N | N/D | N/D | N/D | N/D |
| P | N/D | N/D | N/D | N/D |
| K | N/D | N/D | N/D | N/D |

Se conservan originales, unidades, especies químicas, rangos declarados y
procedencia. Transmisión, repetibilidad y exactitud tienen estados distintos.
No se inventan humedad, CE, coordenadas, coeficientes ni porcentajes de confianza.
Un CRC válido no acredita que una magnitud sea químicamente comparable.

Los modelos se entrenan por analito, con predictores efectivamente medidos,
ponderación por muestra física y validación independiente agrupada. Los pares
sintéticos no pueden promover una calibración productiva. Los ensayos numéricos
de modelos validados se ejecutan únicamente en la base aislada de pruebas; no
constituyen informes de laboratorio auténticos ni perfiles de producción.

## 3. Estadística

Muestras físicas independientes: **0**. Repeticiones físicas: **0**. Variables
explicativas empíricamente verificadas: **ninguna**. MAE, RMSE, sesgo, R² e
incertidumbre de N/P/K frente a laboratorio: **N/D**. La calibración empírica no
pudo validarse.

La comparación reproducible de filtros es un ensayo de software con la secuencia
sintética `15.2, 15.4, 45.0, 15.5, 15.3` y una referencia numérica constante `15.4`:

| Método | Valor central | MAE sintético | RMSE sintético | Sesgo sintético |
|---|---:|---:|---:|---:|
| Sin filtro | 45.00 | 6.000 | 13.238 | 5.880 |
| Promedio centrado | 21.28 | 1.256 | 2.632 | 1.136 |
| Mediana centrada | 15.40 | 0.080 | 0.110 | -0.040 |

Los extremos conservan originales: no hay padding ni muestras inventadas. En
dos puntos independientes con cambio de 10 a 100, los tres métodos conservan
el salto. Cambios de punto, suelo, profundidad, decodificador, unidad y huecos
interrumpen las series; volver al punto A después de B no une ambas secuencias.
Este ensayo no demuestra que la mediana sea el filtro óptimo de la sonda.

Se verifican sesgo constante, regresión simple/múltiple, coeficientes conocidos,
colinealidad, datos faltantes, grupos contaminados, falta de mejora y versiones.
La aplicación de un perfil se restringe a dispositivo, contexto, unidades,
estado/versión y rangos entrenados. Intervalos marginales no garantizan soporte
conjunto multivariable. No se extrapola ni se estima incertidumbre sin evidencia.
El [plan de campaña](sensor-calibration-plan.md) define la validación humana y
la justificación del tamaño muestral; mínimos algebraicos no equivalen a
suficiencia científica.

## 4. Software

### Arquitectura y alcance

Android reutiliza `flutter_serial_communication 0.2.8`. Un perfil de lectura
documentado alimenta un único parser acotado de Modbus RTU 03/04, con CRC,
longitud, excepciones, fragmentación, timeout, reintentos y liberación. Solo
acepta una respuesta por consulta. Otro protocolo o representación numérica
requiere su decodificador documentado; no se afirma compatibilidad universal.

Flutter asigna UUID y hora del teléfono al validar la trama. Guardar confirma
original y operación mediante la SQLite cifrada existente. Al reconectar se
reutilizan el recibo idempotente y `SyncEngine`; después se procesan lotes
explícitos en FastAPI y los resultados regresan por el mismo diario de cambios.
Un fallo posterior al guardado no elimina el original ni crea otra outbox.
El procesamiento automático admite hasta 200 originales por ejecución; grupos
mayores requieren una operación controlada. SQLite v1→v2 añade índices y estado
inferido mediante HMAC por cuenta, preservando ciphertext, AAD, claves y cola.

La migración PostgreSQL nueva `1a2b3c4d5e6f` es aditiva, con un solo head. Hace
opcionales las proyecciones antiguas para variables ausentes y añade el sobre
original y `received_at`; las filas históricas conservan recepción desconocida.
Crea `reading_results`, `sensor_calibration_pairs` y `sensor_calibrations`, con
historial inmutable, unicidad, RLS y revocación explícita de permisos heredados
para `PUBLIC`, `anon` y `authenticated`. No se cambian migraciones históricas.

`reading_results` conserva todas las versiones; `Reading.derived_results` es
la proyección sincronizada. La huella de entradas, algoritmo, configuración y
modelo permite reintentos sin duplicar resultados. No hay reprocesamiento
masivo automático al promover modelos.

Diagnóstico y fertilización rechazan nuevas lecturas v1 como fuente de dosis
definitivas mientras falte comparabilidad agronómica. No se cambian ecuaciones,
JWT ES256, issuer, audiencia, expiración ni MFA. No hay nuevas dependencias,
servicios ML, workers ni colas externas. Los lockfiles permanecen intactos.

### Pruebas y evidencia

La evidencia local se conserva en `tmp/sensor/` y en
`app_flutter/.dart_tool/sensor-validation/`, ambos ignorados. Los resultados
sanitizados y sus hashes se incluyen en [sensor-evidence.json](sensor-evidence.json).
Las credenciales y JWT de fixture no se incorporan al repositorio.

| Prueba | Resultado | Alcance/evidencia |
|---|---|---|
| Backend completo con PostgreSQL real | PASS | 200 pruebas, 32.670 s; incluye 20 pruebas de infraestructura, sin skips |
| Flutter analyze | PASS | Sin incidencias, 8.1 s |
| Flutter completo | PASS | 147 pruebas, 21 s; un skip de fixture HTTP ejecutada separadamente |
| Integración offline original SQLite→HTTP→PostgreSQL | PASS | Reinicio, respuesta perdida, reenvío único y conflicto real |
| Integración sensor SQLite→HTTP→PostgreSQL | PASS | Original conservado, variables ausentes, resultado devuelto y reintento único |
| Migración PostgreSQL y permisos Supabase heredados | PASS | Base nueva aislada, roles/default grants de fixture, inmutabilidad SQL |
| SQLite v1→v2 y fallo durante migración | PASS | Preservación exacta y rollback/reapertura ante fallo inducido de clave |
| Compilación Python y Alembic head único | PASS | Compilación y head `1a2b3c4d5e6f` |
| `alembic check` | FAIL | Drift heredado de #82: `auth.users`, índice agronómico y dos FK `RESTRICT` |
| Lockfiles y cambios de migraciones históricas | PASS | Sin modificaciones respecto de `532ad74` |
| USB/permisos Android/CRC auténtico | NOT RUN | Sin sensor, teléfono ni tramas reales |
| Keychain y ejecución SQLite en teléfono Android | NOT RUN | La fixture usa clave de prueba en memoria y SQLite nativa Linux |
| Build Android, licencias y firma | NOT RUN | No se aceptan licencias ni se modifican keystores |
| Supabase Auth en vivo | NOT RUN | La integración usa JWT ES256/JWKS reales de fixture local |
| Exactitud frente a laboratorio | NOT RUN | Sin muestras pareadas auténticas |
| CI del PR dependiente | NOT RUN | Pendiente de publicación; se actualizará con el resultado observado |

El mismo `FAIL` se reprodujo con el checkout original de `532ad74` y una segunda
base aislada nueva, sin modificar ese checkout. Los siete hallazgos son iguales;
no corresponden a columnas/tablas nuevas de sensor. No se
oculta ni se corrige alterando migraciones históricas en esta tarea. Los logs de
fallos iniciales de instrumentación se preservan junto a los reruns aprobados.

Rendimiento: el benchmark mide procesamiento puro de lotes sintéticos de cinco
y diez observaciones. Los tiempos exactos de esta máquina se conservan en el
JSON; no representan latencia de USB, SQLite Android, red ni laboratorio.
La ejecución local combina Python 3.13.5 en Windows, Flutter 3.44.9/Dart 3.12.2
en Linux y PostgreSQL 17 en un contenedor propio. El puerto de PostgreSQL es
`127.0.0.1:52967`; no se borraron las bases ni recursos de validación.

### Uso, archivos y Git

La [guía](sensor-measurements.md) documenta contrato, endpoints y comandos de
validación. [SENSOR_ACQUISITION.md](../app_flutter/SENSOR_ACQUISITION.md) explica
cómo incorporar un perfil verificado. No se suministra un mapa productivo.

Los archivos modificados y commits se enumeran en la evidencia. Las
responsabilidades se separan entre auditoría, calidad, calibración, persistencia,
adquisición Flutter, sincronización, integración/CI y documentación.

| Commit | Responsabilidad |
|---|---|
| `e55f98d` | Auditoría de la adquisición original |
| `c8f07d4` | Calidad y filtros no destructivos |
| `486902d` | Calibración agrupada y alcance versionado |
| `19df436` | Persistencia, contrato y gates agronómicos |
| `71b6225` | Fronteras de decodificador/suelo y algoritmo v2 |
| `7e1d857` | Infraestructura PostgreSQL, drivers HTTP y CI |
| `f0acdec` | Perfil USB verificado, procedencia y UI |
| `5e4b629` | Procesamiento diferido y migración local segura |

El commit de documentación que contiene este informe registra la campaña,
arquitectura, diagramas y evidencia; la entrega del PR/CI se registra por separado.

Estado de PR/Git: pendiente de publicación del PR dependiente contra
`feat/offline-first-foundation`. No se fusiona ni despliega. La rama Docker,
el checkout original, `main`, PR #76 y la rama del PR #82 se mantienen intactos.

## 5. Pendientes humanos

1. Identificar fabricante, modelo, serie/inventario y manual con versión.
2. Confirmar adaptador USB-C/OTG, VID/PID, chip e interfaz eléctrica.
3. Confirmar tensión/corriente y fuente apropiada antes de conectar la sonda.
4. Verificar permisos Android, desconexión y recepción de tramas auténticas.
5. Documentar parámetros, registros, signo, escala, especies químicas y rangos;
   completar y aceptar el perfil antes de habilitar consultas.
6. Ejecutar estabilización, repeticiones, muestras independientes y laboratorio
   comparable siguiendo el plan; acordar criterios agronómicos de aceptación.
7. Revisar autenticidad/comparabilidad de informes antes de promover perfiles.
8. Aceptar personalmente las licencias Android y ejecutar pruebas de build/firma.

La disponibilidad de estas herramientas de software permite preparar la campaña;
no sustituye ninguno de esos ensayos físicos o químicos.
