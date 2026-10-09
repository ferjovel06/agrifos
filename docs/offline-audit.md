# Auditoría offline-first

Base: `origin/main` en `8182f9f`, checkout independiente. Provider conserva estado en
memoria; los repositorios llaman HTTP directamente. No existe una base local de
dominio ni outbox. Supabase Flutter conserva la sesión mediante su almacenamiento
predeterminado; ese almacenamiento debe sustituirse por almacenamiento seguro.
No existe un módulo general de actividades agrícolas ejecutables.

| Módulo real | Lectura offline | Escritura inicial | Dependencias y conflicto | Sensibilidad / sincronización |
|---|---|---|---|---|
| Fincas | Sí, propias descargadas | No | Propietario; cambios y borrados remotos | Ubicación privada; feed por usuario |
| Parcelas | Sí, descargadas | No | Finca/cultivo/variedad; configuración concurrente | Datos privados; revisiones y tombstones |
| Lecturas de sensor OTG | Sí | Crear | Parcela existente; registro inmutable | Mediciones privadas; UUID e idempotencia |
| Análisis de laboratorio | Sí | Crear y editar | Parcela; código de muestra único; edición concurrente | Datos privados; revisión esperada y ambas versiones |
| Fenología y catálogos | Solo información preparada | No | Cultivo/parcela/plantillas | Configuración agronómica; consulta persistida |
| Fertilización y diagnósticos | Solo resultados previamente preparados | No cálculo remoto offline | Referencias versionadas y medición confirmada | Decisiones agronómicas; no usar clima histórico como actual |
| Pronóstico | Sí | No | Ubicación y producto; caducidad | Caché local privada; respuesta externa compartida sin finca/usuario |
| Alertas climáticas | Solo resultados descargados | No evaluación offline | Pronóstico y finca | Evaluación necesita servidor |
| Finanzas | No en esta entrega | No | Importes/categorías/fecha | Sensible; permanece online |
| Perfil, MFA, recuperación, registro de cuenta | No | No | Supabase y autorización del servidor | Tokens seguros; primer acceso online |

Los repositorios usan `ApiClient`, con timeout de 15 segundos. Los errores de
lectura pueden vaciar el estado mostrado. Las listas HTTP usan offset y no hay
feed de eliminaciones. Los UUID se generan en el servidor, sin clave de
idempotencia ni revisión esperada en el cliente. Las transacciones actuales
confirman dentro de cada repositorio del backend.

Clima: Open-Meteo es primario y MET Norway fallback. El backend deduplica dentro
de un proceso, pero la clave incluye finca, coordenadas y días; reinicios y
workers pierden esa caché. El transporte no conserva `Expires`, `Last-Modified`
ni `Retry-After`, ni soporta 304. MET redondea coordenadas en vez de truncarlas.
El panel conserva una respuesta en memoria durante 30 minutos; Planificación
consulta por su cuenta, siete días frente a tres del panel. IndexedStack mantiene
ambas pantallas vivas, incluso cuando no son visibles.

Decisión: SQLite con Drift (executor nativo en isolate), migración local versionada
y transacciones explícitas. Se reutilizan Provider, `http`, modelos y repositorios;
no se introduce una nueva capa de estado. Se añaden almacenamiento seguro y
señales de conectividad, compatibles con Dart 3.12, Java 17, AGP 9.0.1 y Gradle 9.1
existentes. El backend usará PostgreSQL existente para el feed, recibos de
idempotencia y caché HTTP compartida. Las escrituras iniciales exigen padres ya
descargados: no hay creación offline de fincas/parcelas ni borrado irreversible.

La política de acceso local tendrá una duración explícita y no autorizará llamadas
remotas con tokens caducados. Se conservarán operaciones al salir de una cuenta,
ocultándolas a otras identidades. Las mediciones y payloads locales se cifrarán con
una clave por cuenta protegida por el almacén seguro del dispositivo.

Fuentes de compatibilidad: [Drift nativo](https://drift.simonbinder.eu/platforms/vm/),
[almacenamiento seguro](https://pub.dev/packages/flutter_secure_storage),
[señales de conectividad](https://pub.dev/packages/connectivity_plus).
Políticas externas: [MET Norway](https://api.met.no/doc/TermsOfService),
[Open-Meteo](https://open-meteo.com/en/terms).
