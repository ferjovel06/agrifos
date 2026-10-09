# Estado implementado de Ágrifos

Base verificable: `origin/main` en `8182f9f`; ampliación propuesta en `feat/offline-first-foundation`, octubre de 2026. Describe el repositorio, sin afirmar que el despliegue o APK publicado ya usa ese commit.

| Módulo | Integrado | Límite actual |
|---|---|---|
| Offline-first (rama de propuesta) | SQLite cifrado, cola durable, sync idempotente, revisión de conflictos y clima guardado | Android/device acceptance pendiente; scope detallado en [guía](offline-first.md) |
| Identidad | Supabase Auth, perfil, roles, MFA TOTP | Credenciales y servicios externos requeridos |
| Finca y parcelas | Registro/consulta/edición, cultivo, variedad, densidad y etapa | Catálogo de cultivos no equivale a motores validados para todos |
| Sensor (propuesta dependiente del PR #82) | Perfil/documentación y dispositivo explícitos, parser acotado, procedencia parcial, calidad, filtros agrupados y calibración versionada | Hardware y precisión frente a laboratorio NOT RUN; no perfil físico ni coeficientes productivos activados. [Guía](sensor-measurements.md) |
| Laboratorio | Captura NPK, Ca/Mg/S, pH, CE, MO, CIC, textura y métodos | Balance productivo solo N/P₂O₅/K₂O |
| Fertilización | Escenarios minerales, plan joven, snapshots y recuperación | Apoyo a decisiones, no garantía agronómica |
| Orgánico | Bocashi, Biol, Compost de pulpa y balance total comparativo | Referencia parcial; sin aplicación aprobada ni calendario ejecutable |
| Clima | Pronóstico por finca, alertas lluvia/calor y calendario climático | Sin matriz de infiltración ni bloqueo automático del plan por clima |
| Fenología | Plantillas y registros por parcela, selección de etapa | Sin gestión automática completa de cohortes ni hitos en calendario climático |
| Finanzas | CRUD ingresos/egresos, tablero y flujo mensual por finca | Producción modelada sin CRUD en router; sin punto de equilibrio |

## Finanzas: interpretación de métricas

`GET /finances/dashboard` recibe `farm_id`, fecha `as_of` y `months` (2–12, predeterminado 6). Periodo actual: primer día del mes hasta fecha de corte. Compara con el mes anterior hasta el día equivalente, limitado por su duración.

Balance = ingreso − egreso. Margen = balance/ingreso × 100; sin ingreso se devuelve `null`. Variación de balance usa valor absoluto del balance anterior; base cero produce `null`. Cambio de margen se expresa en puntos porcentuales. Proyección anual = ingreso acumulado del año × días del año/días transcurridos. No considera estacionalidad ni precios futuros. Importes persistidos usan `Numeric(12,2)` y cálculos monetarios `Decimal`.

## Qué queda fuera de esta sincronización

La ampliación local de nutrientes complementarios no está en esta base fusionada. Tampoco se documentan como existentes fertilizantes comerciales complementarios, integración Bluetooth, cálculos para maíz. Café es el alcance inicial y la arquitectura es escalable.

## Fuentes de verdad y mantenimiento

Contratos: schemas y routers incluidos en `backend/app/main.py`. Persistencia: modelos SQLAlchemy y migraciones `backend/alembic/`. El archivo `supabase/config.toml` configura servicios locales, no reemplaza Alembic. Interfaz: repositorios/entidades/pantallas Flutter. Algoritmos: servicios y configuración activa versionada.

Cada cambio fusionado debe revisar README, guía de evaluación, documento del motor y diagramas afectados. Los Mermaid ER representan los modelos del código, no una inspección de una base desplegada. Los PNG/SVG previos y PDF son material histórico o referencias de diseño; no prueban implementación actual.
