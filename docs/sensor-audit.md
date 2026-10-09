# Auditoría de adquisición NPK

Fecha: 9 de octubre de 2026. Base: PR #82 abierto, `532ad74c919bc0b620b4b20f1d0d7e568a8d20b6`.
Trabajo aislado en `feat/npk-measurement-reliability`. No se modifica el PR #76,
la rama Docker, `main`, la rama offline ni datos existentes. No hay `AGENTS.md`
en el checkout o sus directorios superiores inspeccionados.

## Qué existía realmente

La clasificación correcta es **A, controlador USB implementado en software,
con compatibilidad física NOT RUN**. No encontramos generación de datos
simulados en la ruta de adquisición de producción. Una pantalla con valores,
un parser o una compilación no acreditan lectura física de la sonda.

1. `MainActivity.kt` entrega el intent de conexión USB a Dart mediante
   `agrifos/usb_attach`. El filtro XML heredado contiene VID/PID decimal
   `6790/29987`; no es evidencia de que ese adaptador esté conectado ni de que
   identifique un modelo de sonda.
2. `SensorProvider` escucha conexión/desconexión y llama `UsbSensorService`.
3. `UsbSensorService` usa **flutter_serial_communication 0.2.8**, no `usb_serial`.
   Enumeraba dispositivos y elegía `devices.first`. Abría a 9600 baudios y asumía
   Modbus RTU, dirección 1, función 03, registros 0–6. Consultaba cada dos segundos.
   Ese intervalo y los 500 ms iniciales carecen de validación experimental.
4. Recibía listas de bytes por EventChannel, comprobaba CRC16 y decodificaba
   humedad/temperatura/pH divididos entre diez, CE sin escala y N/P/K sin escala.
   Es un mapa heredado sin manual ni tramas auténticas. CRC correcto demuestra
   integridad del mensaje, no que el mapa, las unidades o la química sean correctos.
5. El buffer no tenía política explícita de tamaño. El parser recurría sobre CRC
   inválido y no drenaba todas las tramas válidas de un único evento. No había
   timeout de respuesta acotado ni manejo de excepciones Modbus. Reintentos del
   provider podían dejar listeners y valores anteriores activos.
6. Guardar enviaba siete valores a `ReadingsRepository.submitReading`; CE se
   dividía entre 1000 suponiendo µS/cm. No se conservaban trama, perfil, modelo,
   sesión ni hora de adquisición. El guardado offline asignaba hora de guardado.
7. En nativo, `OfflineRuntime.save('readings', ...)` confirma entidad y outbox
   en SQLite cifrado. `SyncEngine` entrega la operación al backend por
   `POST /sync/operations`; ID/recibo/hash existentes evitan duplicación.
8. `ReadingCreate` valida campos; el router verifica cuenta/finca/parcela y
   persiste `Reading` en PostgreSQL. `GET /sync/changes` devuelve datos de la
   cuenta. La vía online utiliza `POST /readings`, el mismo modelo persistido.
9. El diagnóstico ya se describe como preliminar. La vía de fertilización
   acepta estados agronómicos de sensor, pero no acredita comparabilidad química
   ni calibración de la sonda. Sus ecuaciones no deben sustituirse por un filtro.

## Información física pendiente

| Información | Evidencia disponible | Estado |
|---|---|---|
| Fabricante, modelo y número de serie | Ninguna | NOT RUN |
| Conector y adaptador USB-C/OTG real | Descripción del usuario; sin identificación física | NOT RUN |
| VID/PID, chip, puerto del dispositivo conectado | Literal XML heredado; ninguna enumeración real | NOT RUN |
| USB CDC, serial TTL o conversor USB-RS485 | No confirmado | NOT RUN |
| Tensión/corriente y fuente de alimentación | No disponibles; USB no acredita suficiencia | NOT RUN |
| Protocolo, baud rate, paridad y framing | Supuestos en el código, sin manual | NOT RUN |
| Registros, signo, orden, escala y unidades | Mapa heredado sin respaldo | NOT RUN |
| Analito: N/NO3-N/NO3, P/P2O5, K/K2O | No identificado | NOT RUN |
| Rangos, estabilización y repetibilidad | Sin ensayo ni especificaciones | NOT RUN |
| Tramas auténticas y lectura Android real | No disponibles | NOT RUN |
| Comparación con laboratorio e incertidumbre | Cero muestras independientes | NOT RUN |

No se ejecutarán sondeos eléctricos, escrituras de registros ni consultas con
mapas supuestos. El perfil físico debe identificarse y documentarse antes de
habilitarlo. Las fixtures sintéticas solo verifican lógica de software.

## Fuentes verificadas y límites

La [documentación del paquete 0.2.8](https://pub.dev/packages/flutter_serial_communication/versions/0.2.8)
declara soporte Android OTG y reutiliza usb-serial-for-android. Su código instalado
es la referencia para permisos, framing y cierre; conservar el paquete evita
actualizaciones ajenas al alcance. La [API USB Host de Android](https://developer.android.com/develop/connectivity/usb/host)
describe enumeración, autorización y liberación de la conexión. Ninguna fuente
confirma esta sonda.

El [manual NIST sobre detección de observaciones atípicas](https://www.itl.nist.gov/div898/handbook/eda/section3/eda35h.htm)
fundamenta conservar e investigar observaciones sospechosas. La
[calibración e incertidumbre de NIST](https://www.itl.nist.gov/div898/handbook/mpc/section3/mpc3672.htm)
requiere evidencia experimental; mediana/MAD no corrigen por sí solos sesgo
analítico. No hay fundamento para prometer exactitud de laboratorio.
