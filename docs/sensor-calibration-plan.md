# Campaña de calibración y aceptación física

Este plan prepara un ensayo; no acredita precisión. Hay **cero muestras reales
independientes y cero pares de laboratorio disponibles** en esta entrega.

## Antes de energizar o consultar

Identificar fabricante/modelo/serie y conseguir el manual específico. Registrar
el adaptador, VID/PID real, conversor y puerto; distinguir USB serial, USB-RS485
y alimentación de la sonda. Verificar tensión/corriente y compatibilidad OTG
mediante documentación y personal competente. No conectar eléctricamente
interfaces incompatibles ni asumir que USB-C proporciona la alimentación necesaria.

Confirmar protocolo, comandos exclusivamente de lectura, registros, orden de
bytes, signo, escalas, unidades, analitos y rangos. Si se confirma Modbus RTU,
registrar dirección y función; validar bytes/CRC contra tramas auténticas. Si es
otro protocolo, no habilitar el parser Modbus para ese dispositivo.

Configurar el perfil y documentar quién/qué evidencia lo verifica. Comparar cada
valor decodificado con la documentación y una indicación independiente disponible.
Probar permiso concedido/denegado, desconexión durante recepción, alimentación
inestable (solo si el equipo la informa), timeout y reapertura. No escribir
registros de calibración ni cambiar configuración del hardware.

## Piloto de repetibilidad

El usuario identifica finca/parcela/punto y profundidad; un mismo punto no es una
nueva muestra independiente por recibir otra lectura. Documentar contacto con
suelo, procedimiento de inserción, limpieza entre muestras y tiempos. Medir la
evolución temporal desde inserción, retiradas/reinserciones y sesiones separadas.
No derivar estabilidad solo de una serie constante: podría estar congelada o sesgada.

El tiempo de estabilización, intervalo y número de repeticiones se escogerán a
partir del manual y del piloto, conservando la evidencia y sus limitaciones.
Repeticiones, dispersión y MAD describen repetibilidad. No representan por sí
solas error frente a laboratorio ni justifican un porcentaje de confianza.

## Referencia química comparable

Cada muestra física recibe un identificador estable. Registrar finca/parcela,
fecha, profundidad, procedimiento, humedad/condiciones, laboratorio, método,
analito, unidad, base de reporte e incertidumbre disponible. Las repeticiones de
una muestra comparten ese identificador durante entrenamiento y validación.

La comparación necesita una justificación explícita entre la magnitud del sensor
y la referencia. No equiparar N con NO3-N/NO3, P con P2O5, K con K2O ni fósforo
de extractantes distintos. mg/L, ppm y mg/kg no se convierten automáticamente.
El laboratorio o especialista debe confirmar el alcance de una comparación;
registrar un texto de método no demuestra equivalencia química.

Seleccionar muestras que cubran rangos de concentración, humedad medida, tipos
de suelo y parcelas de café donde se pretende usar el dispositivo. Incorporar
replicados físicos independientes, controles del laboratorio y muestras de control
repetidas entre días. No contar las repeticiones instrumentales como tamaño n.

El piloto determinará dispersión, rangos y heterogeneidad. Justificar el tamaño
de campaña con esos datos, la cantidad de predictores, la precisión requerida y
el comportamiento de curvas de aprendizaje/errores de validación. Los mínimos
numéricos que exige el software solo evitan regresiones indeterminadas; **no son
un tamaño de muestra agrícola suficiente**.

## Entrenamiento, promoción y uso

Comparar sensor crudo, sesgo constante, regresión simple y regresión múltiple por
nutriente. Incorporar humedad/temperatura/pH/CE solo cuando realmente se midan
y cuando la hipótesis física y datos independientes respalden el predictor.
Revisar datos faltantes, colinealidad y residuos por rango, parcela y suelo.

Separar muestras físicas completas; cuando el objetivo sea generalizar a nuevas
parcelas o días, reservar esos grupos en su totalidad. La separación técnica por
ID de muestra no garantiza automáticamente generalización por parcela o tiempo.
El conjunto de prueba independiente no se usa para escoger repetidamente modelos.

Conservar MAE, RMSE, sesgo, R² (N/D si la referencia es constante), residuos y
errores por subgrupo antes/después. Aceptar solo mejoras independientes dentro
del alcance ensayado, sin fallos de subgrupo inaceptables. Examinar también sesgo,
condiciones de aplicación y relevancia agronómica; pasar un gate de software no
equivale a certificación metrológica. Las fixtures sintéticas no se promueven.

Mantener dispositivo, unidad, analito, base de entrada cruda/filtrada, variables,
rango, versión y evidencia de cada perfil. El software rechaza extrapolación y
contextos incompatibles. No se genera intervalo de incertidumbre sin evidencia
que permita estimarlo. Una estimación calibrada no demuestra disponibilidad de
nutrientes ni autoriza automáticamente una dosis definitiva.

Reprocesar un lote explícitamente identificado. Conservar originales y resultados
anteriores; no activar reprocesamiento masivo al publicar un modelo. Para mapas,
registrar coordenadas/precisión con consentimiento; no inventarlas ni interpolar
superficies continuas con una densidad de muestras no validada.
