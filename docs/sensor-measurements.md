# Adquisición, calidad y calibración de mediciones

Propuesta `feat/npk-measurement-reliability`, dependiente del PR #82 en `532ad74`.
La [auditoría](sensor-audit.md) describe qué hacía el código anterior. Los
[resultados](sensor-validation.md) distinguen software, infraestructura y pruebas
físicas. No hay un perfil de sonda activado ni un modelo empírico productivo.

## Adquisición Android

Se conserva `flutter_serial_communication 0.2.8`; no se incorporan paquetes ni
otro puente Kotlin. El filtro Android para un VID/PID supuesto se elimina.
Enumerar un dispositivo no envía comandos. `SensorProvider.availableDevices()`
y `selectDevice(profile, device)` exigen selección explícita y un `SensorProfile`
documentado/verificado antes de abrir, solicitar permiso Android o consultar.

El perfil exige modelo, identificación física de la unidad, evidencia, VID/PID,
baud rate, datos/parada/paridad, protocolo de lectura, dirección/función,
registros, escala/signo/unidad/analito, timeout, intervalo y reintentos acotados.
Debe completarlo el responsable técnico después de revisar el manual y efectuar
la aceptación física. No existe un valor predeterminado que permita copiar el
mapa de una sonda parecida. El adaptador y la alimentación se comprueban aparte.

Solo se implementa el decodificador Modbus RTU de lectura 03/04, sujeto a perfil
verificado; otro protocolo requiere su propio decodificador documentado. CRC16,
dirección, función, longitud, excepciones, fragmentación, timeout y límite de
buffer se comprueban en una sola implementación. El transporte acepta una
respuesta por solicitud; no convierte duplicados en mediciones independientes.
Una desconexión o error invalida la muestra visible y libera el puerto. Nunca
se sustituyen fallos por NPK artificial. Las fixtures prueban estos estados,
pero no certifican permisos, alimentación ni USB en un teléfono real.

El identificador temporal USB de Android no identifica persistentemente la sonda
([documentación Android](https://developer.android.com/reference/android/hardware/usb/UsbDevice#getDeviceId())).
La identidad física usada para calibración debe proceder de serie/inventario y
evidencia documentada; VID/PID solo sirve para seleccionar el transporte.

## Contrato y procedencia

`Reading` sigue siendo el único original persistido. Su UUID es el
`measurement_id`: se asigna al validar la trama y se reutiliza al guardar,
reiniciar/reintentar y sincronizar después del commit local. Una captura que
todavía no se guardó no sobrevive al cierre de la aplicación.
`measurement.contract_version=1` incorpora
sesión, unidad física, modelo, protocolo y versión del decodificador, hora de
adquisición UTC y variables realmente recibidas. `acquired_at` es la hora del
teléfono al validar la trama completa, no un reloj interno de la sonda. El backend añade su hora de
recepción. En filas históricas esa hora es desconocida (`null`), sin inventar
una fecha de recepción al aplicar la migración.

Cada variable conserva `raw_value`, unidad, analito, rango declarado opcional
y `read_status`. N/NO3-N/NO3, P/P2O5 y K/K2O permanecen distintos. mg/L, ppm y
mg/kg no se convierten automáticamente. Únicamente CE tiene equivalencias
dimensionales documentadas: uS/cm / 1000 = dS/m; mS/cm = dS/m. Una variable
incompatible con las columnas antiguas permanece en el sobre crudo, con su
proyección antigua `null`. Las variables ausentes también permanecen `null`.

Antes de guardar se identifica punto y opcionalmente profundidad/tipo de suelo
documentado. Finca/parcela se obtienen de la selección local; cuenta y propiedad
se verifican de nuevo por JWT en el servidor. Coordenadas, precisión y
consentimiento son opcionales: no se generan coordenadas ni se solicita ubicación
para fabricar un punto. El contrato permite incorporarlas mediante una captura
con permiso válido; no hay interpolación espacial ni mapa continuo nuevo.

La trama conservada se limita a 256 bytes por **captura guardada**, cifrada
localmente con los datos privados. No hay registro continuo de tramas ni archivos
de depuración crudos. Los originales y derivados se conservan para trazabilidad;
no se añade purga automática de datos. La retención administrativa y el tamaño
de una campaña deben planificarse antes de despliegues prolongados.

Las lecturas históricas sin sobre mantienen su contrato anterior de siete
campos. Esos límites son validación heredada de aplicación, no rangos del
fabricante. Los datos v1 conservan valores fuera del rango declarado para
auditoría y reciben advertencias/estado técnico; no se recortan silenciosamente.

## Calidad y procesamiento diferido

Transmisión, repetibilidad y exactitud tienen estados independientes y códigos
de razón. Se detectan valores no finitos, unidades incompatibles, timestamps
inconsistentes, duplicados, falta de variables, rangos declarados y fallos de
transmisión. MAD, saltos y estabilización admiten umbrales configurables solo
con evidencia documentada; no se inventa un rango universal NPK. Sin tiempos
empíricos se conserva `STABILIZATION_NOT_ESTABLISHED`.
Los umbrales con evidencia se configuran mediante `ProcessingConfig` en Python;
la API actual expone método/ventana y conserva umbrales no establecidos mientras
no exista una configuración técnica documentada.

`POST /readings/process` recibe UUID explícitos (máximo 200), ventana impar
3–31, `method=none|mean|median` y, optativamente, ID de una calibración validada.
La mediana por defecto es una opción de software para repeticiones comparables,
no una selección óptima demostrada para el hardware. Se procesa cada analito
en segmentos consecutivos de un mismo punto/sesión/dispositivo/parcela,
protocolo, perfil decodificador, suelo, profundidad y unidad. Huecos, cambio de punto o tiempo invertido
interrumpen el segmento. La ventana centrada solo se aplica a lotes completos;
extremos y series cortas conservan originales y sus limitaciones.

La ruta offline confirma primero el original y su operación en SQLite cifrado.
Al reconectar se entrega mediante `POST /sync/operations`, usando el recibo y
el coordinador existentes. El procesamiento sucede después de confirmar el
original. Un fallo de procesamiento conserva la lectura y permite reintentar;
una huella sobre entradas/configuración/modelo evita duplicar derivados.
Los resultados vuelven por el mismo diario `GET /sync/changes`. No hay una
segunda outbox, servicio ML, worker externo ni dependencia de internet para
recibir y guardar la trama.

SQLite pasa de esquema v1 a v2 mediante una migración aditiva de metadatos de
procesamiento. Originales, ciphertext, AAD, claves y cola se conservan. Los
grupos se identifican mediante HMAC por cuenta, sin dejar contexto privado en
claro. Se envía la secuencia completa de la sesión para conservar cambios de
punto. La UI inicia una sesión de muestreo nueva cuando cambia el contexto.
El procesamiento automático es acotado; un grupo grande requiere una
operación de lote explícita y revisión de límites, sin ocultar lecturas pendientes.

## Pares, perfiles y resultados históricos

`POST /calibrations/pairs` vincula una lectura cruda a muestra física y referencia:
laboratorio/informe, fecha, procedimiento/profundidad, humedad, método, analito,
unidad, base, incertidumbre disponible y justificación de comparabilidad. Se
rechazan cambios de especie/unidad y profundidad incompatible. Una misma
lectura o contexto físico no puede renombrarse para simular muestras independientes.
La autenticidad de un informe de laboratorio requiere revisión humana; la API
no verifica por sí sola una institución ni una equivalencia química.

`POST /calibrations/train` recibe pares, grupos reservados, predictores realmente
medidos, tipo de modelo, ID/versión y evidencia. Calcula regresión por analito
mediante QR centrado/escalado o sesgo constante, sin NumPy/scikit-learn nuevo.
Registra un **candidato**; no activa automáticamente el resultado. Las
repeticiones pesan como una muestra física. Coeficientes/rangos no se reciben
del cliente como autorización para usar un modelo.

`POST /calibrations/{id}/validate` recalcula MAE/RMSE/sesgo/R² y residuos contra
pares independientes reservados. Rechaza fixtures sintéticas, falta de mejora,
contaminación de grupos, cambios de datos y empeoramiento en subgrupos observados.
Los mínimos algebraicos no acreditan suficiencia científica: véase la
[campaña](sensor-calibration-plan.md). No se calcula incertidumbre ficticia.

La aplicación de un modelo exige versión/estado, dispositivo físico, contexto
exacto de modelo/protocolo/decodificador, parcela/suelo y profundidad compatibles,
predictores técnicamente válidos y valores dentro del rango entrenado. La base
de entrada inicial es **cruda**, sin aplicar a valores filtrados un modelo
entrenado con crudos. Se rechazan extrapolación y valores sospechosos. Los
intervalos marginales no garantizan soporte conjunto multivariable ni validan
suelos/parcelas no ensayados. Retirar un perfil bloquea nuevos usos y conserva
evidencia anterior.

`GET /readings/{id}/results` conserva todas las versiones. `reading_results` es
historial canónico append-only; `Reading.derived_results` es su proyección para
sincronización. Reprocesar crea otro resultado, nunca sobrescribe el original
ni versiones anteriores. No se ejecuta un lote masivo al crear/promover modelos.

## Diagnóstico, fertilización y operación

La UI presenta valores medidos y procesados con fecha, modelo y advertencias,
sin porcentajes de confianza. Las nuevas lecturas v1 no se clasifican ni producen
dosis definitivas por la ruta agronómica heredada: ambos endpoints responden
con una advertencia estructurada mientras falte un método agronómico comparable.
La estimación calibrada no se interpreta como nutriente disponible. Las
ecuaciones agronómicas y los métodos de laboratorio existentes se conservan.

Instalar y validar con lockfiles existentes, desde cada carpeta:

```powershell
# backend, con DATABASE_URL/SUPABASE_URL propios de desarrollo
uv sync --locked
uv run alembic upgrade head
uv run alembic heads
uv run python -m unittest discover -s tests -v
# app_flutter
flutter pub get --enforce-lockfile
flutter analyze
flutter test
```

Para infraestructura real usar exclusivamente una base fixture `agrifos_offline_*`
en loopback, como describe [offline-validation.md](offline-validation.md), y:

```powershell
# backend
uv run python -m unittest tests.test_offline_postgres tests.test_sensor_postgres
# raíz, Flutter disponible (o --docker-tool-container propio)
uv run --project backend python scripts/offline_integration.py --sensor
uv run --project backend python scripts/sensor_filter_benchmark.py
```

No se aceptan licencias Android ni se cambian keystores automáticamente. La
integración usa SQLite/HTTP/PostgreSQL reales y JWT ES256 con JWKS de fixture;
eso no sustituye Supabase Auth en vivo ni hardware USB.
