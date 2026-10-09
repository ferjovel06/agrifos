# Adquisición verificable en Android

La aplicación no incluye un perfil de producción ni transmite solicitudes al
conectar un adaptador genérico. El fabricante, modelo, interfaz eléctrica,
alimentación, VID/PID, protocolo y manual de la sonda siguen pendientes de
validación física. Las tramas de `test/support/sensor_fixture.dart` son
exclusivamente sintéticas y nunca se registran como datos de ejecución.

El controlador conserva `flutter_serial_communication` 0.2.8 del lockfile.
Su plugin Android pide el permiso USB al abrir el dispositivo y permite
configurar baudrate, bits, paridad y parada con `setParameters`. No se añadió
un puente nativo ni un filtro VID/PID supuesto. El rechazo del permiso puede
indicar también que el driver no logró abrir el puerto; el plugin no separa
todos los motivos físicos. La alimentación insuficiente no se puede medir por
software con esta interfaz.

## Incorporar un perfil real

Después de revisar el manual y verificar el equipo, registrar un `SensorProfile`
en el código de configuración revisado. Debe aportar referencia documental,
identidad de la unidad física (`physicalDeviceId`, serial o inventario) y evidencia
de esa identidad (`identityEvidence`), VID/PID del adaptador, parámetros seriales,
dirección, función de lectura 3 o 4, registro inicial, cantidad de registros,
variables presentes, analitos, unidades, escala, timeout, intervalo y reintentos.
`verified` representa esa revisión; no valida por sí mismo el dispositivo real.
No usar los identificadores transitorios Android como identidad de calibración.

Solo se implementó Modbus RTU con registros de 16 bits en orden big endian,
interpretación entera con signo opcional y escala positiva documentada. Otro
protocolo, tipo numérico u orden requiere una implementación comprobada; no debe
adaptarse el mapa de otra sonda. No hay comandos de escritura de registros.

El punto de integración deliberadamente pequeño es:

```dart
final devices = await sensorProvider.availableDevices();
// La interfaz de configuración debe mostrar VID/PID y dejar elegir a la persona.
// selectedDevice procede de esa selección, reviewedProfile de la revisión real.
await sensorProvider.selectDevice(reviewedProfile, selectedDevice);
await sensorProvider.connectAndListen();
```

No se selecciona `devices.first` ni se reconecta automáticamente un dispositivo
desconocido. La reconexión manual reutiliza la selección revisada y crea una sesión
nueva. Una respuesta completa se acepta una vez por solicitud; copias adicionales
no generan nuevas mediciones. Timeout y CRC inválido vacían la muestra visible;
los reintentos de lectura tienen un límite en el perfil. Una desconexión invalida
la captura y las respuestas tardías no restauran valores antiguos.

## Procedencia y guardado

`acquired_at`/`recorded_at` se fijan cuando el teléfono reconstruye y valida la
trama. Son tiempo del teléfono, no un timestamp interno del sensor ni garantía
de reloj metrológico. El guardado conserva ese instante y el UUID de captura.
PostgreSQL registra aparte la recepción. La muestra incluye solo las variables
realmente documentadas y recibidas; ausencias se conservan como `null`.

Los valores crudos son los registros decodificados con la escala documentada.
La evidencia hexadecimal conserva el registro binario original hasta 256 bytes
por captura guardada. No hay log ilimitado de cada poll. N/NO3-N/NO3,
P/P2O5 y K/K2O no se equiparan. Solo N, P y K en mg/kg se presentan en los campos
de compatibilidad agronómica; concentraciones incompatibles permanecen en la
envoltura original. CE uS/cm se convierte dimensionalmente a dS/m al decodificar,
una sola vez; mS/cm y dS/m son dimensionalmente equivalentes.

El rango opcional procede del perfil documentado. Un valor fuera de él se conserva
con estado `suspect`, sin corregirlo ni atribuirle una exactitud. CRC correcto,
repetibilidad y exactitud de laboratorio son propiedades distintas.

Al capturar, se pide punto de muestreo y se admiten profundidad y tipo de suelo
documentado. Cambiar parcela o contexto inicia una sesión de muestreo nueva: volver a un
punto anterior no mezcla las dos visitas como repeticiones continuas. No se
obtienen ni inventan coordenadas; el contrato admite ubicación solo con
consentimiento, precisión y coordenadas válidas.

Se reutilizan `ReadingsRepository`, `OfflineRuntime`, SQLite cifrado y su outbox.
Repetir el guardado de la misma captura devuelve la entidad existente; cambiar
su evidencia con el mismo UUID se rechaza. La migración SQLite v1→v2 añade estado
inferido de procesamiento e índice de grupo HMAC por cuenta. Conserva ciphertext,
AAD, operaciones y checkpoint; no agrega una segunda cola.

Al reconectar, el mismo motor sincroniza originales, descarga cambios, solicita
procesamiento por sesión y ruta completa y vuelve a descargar resultados
versionados. El grupo HMAC por cuenta depende únicamente de la sesión: no separa
la ruta local por parcela, dispositivo, decodificador ni punto. El backend conserva
el orden y segmenta los cambios de contexto, sin unir visitas interrumpidas.
La solicitud utiliza mediana centrada, ventana 5 y ninguna calibración activada
automáticamente. Los extremos y series cortas mantienen el original con
limitaciones estadísticas del backend. Se solicitan como máximo 200 originales
por ejecución; un grupo mayor exige un lote explícito. Si falla el procesamiento,
los originales siguen sincronizados y el procesamiento pendiente se reintenta en
la siguiente sincronización solicitada o reconexión. No hay timer ni worker nuevo.

## Validación

```sh
flutter pub get --enforce-lockfile
flutter analyze --no-pub
flutter test --no-pub
```

Las pruebas de parser, transportes deterministas, almacenamiento cifrado y
migración SQLite son verificaciones de software. Permisos Android reales, USB-C,
alimentación, identidad física, tramas auténticas y compatibilidad de la sonda:
**NOT RUN** hasta disponer del equipo. No se aceptan licencias Android ni se
modifican keystores. Exactitud y calibración agrícola requieren muestras pareadas
con laboratorio; ningún fixture demuestra precisión real.
