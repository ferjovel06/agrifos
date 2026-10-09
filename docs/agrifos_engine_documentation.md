# Motor de fertilización de Ágrifos: contrato y cálculo implementados

Revisión: 8 de octubre de 2026. Base: `main`, `f986ccb`, PR #74. Motor mineral: `coffee-fertilization-1.0.1`.

## Alcance y fuentes de verdad

El motor implementado está orientado a café. Su arquitectura es escalable; otros cultivos requieren trabajo de desarrollo y validación. Esta documentación describe el código integrado, no las propuestas anteriores sobre maíz, calibración automática, cohortes o dosificación complementaria.

Consultar `backend/app/services/fertilization_service.py`, `agronomic_config.py`, `organic_fertilization.py`, `backend/app/schemas/fertilization.py`, el router y el repositorio de planes. Las referencias minerales se cargan de PostgreSQL mediante `repositories/agronomic_reference.py`: productos, rangos, factores, eficiencias y calendario pertenecen a un conjunto versionado. Una configuración incompleta se rechaza.

## Entradas y unidades

La petición identifica parcela, rendimiento, unidad y etapa del fruto. Debe proporcionar exactamente una evaluación `soil` o un `lab_analysis_id`. `reading_id` solo acompaña una evaluación de sensor y debe pertenecer a la parcela. El servidor obtiene cultivo, variedad, edad, superficie y densidad de la parcela y verifica autorización.

Rendimientos admitidos: `kg_green_ha`, `qq_gold_ha`, `qq_cherry_ha`. Oro se convierte con `kg_per_qq_gold`; cereza usa además `cherry_to_green_factor`. Estos factores pertenecen a la configuración activa. Nunca interpretar un rendimiento por finca como rendimiento por hectárea.

`soil` contiene estados N/P/K: `deficient`, `probable_response`, `adequate`, `high`; pH y CE son opcionales. Laboratorio y fuente mixta requieren los métodos de P y K. El análisis persistido se clasifica con los rangos activos. Exigir un método no significa que el motor implemente una conversión universal entre extractantes.

El sensor es una fuente orientativa: no se implementa una curva automática de calibración NPK según temperatura/humedad ni una conversión de toda la masa de suelo a disponibilidad nutricional. Ca/Mg/S capturados en laboratorio no forman parte del balance productivo actual; B/Zn y otros micronutrientes tampoco tienen una dosificación integrada.

## Balance productivo

Para cada nutriente i en N, P₂O₅ y K₂O:

```text
exportación_i = rendimiento_verde_kg_ha / 1000 × índice_extracción_i
demanda_i = exportación_i × (1 + mantenimiento) × factor_varietal_i
crédito_i = exportación_i × crédito_configurado_para_estado_i
requerimiento_i = max(0, demanda_i − crédito_i) / eficiencia_i
si estado_i == high: requerimiento_i = 0
```

El crédito es una aproximación por clase de fertilidad. No es una medición de kg disponibles derivada de ppm, profundidad o densidad aparente. Los resultados muestran exportación, demanda, crédito y requerimiento separados; los valores se redondean para el contrato. La eficiencia se aplica una vez al requerimiento mineral.

## Escenarios minerales y cantidades

Económico y Bajo cloruro emplean productos del catálogo activo. La selección considera fuentes fosfatadas (DAP/MAP/TSP), su aporte concomitante de N, la fuente potásica y la urea restante. Se deben consultar las condiciones exactas del servicio; no es una optimización comercial basada en precios. El catálogo obligatorio incluye Urea, DAP, MAP, TSP, KCl, sulfato de potasio y MgO. La presencia de MgO en el plan de café joven no constituye un algoritmo general de déficit de Mg productivo.

```text
kg/manzana = kg/ha × hectáreas_por_manzana
g/planta = kg/ha × 1000 / plantas_por_hectárea
cantidad_parcela_kg = kg/ha × superficie_ha
```

N, P₂O₅ y K₂O son nutrientes, no kg de fertilizante. No mezclar P elemental con P₂O₅, ni K elemental con K₂O. El análisis garantizado del producto determina sus aportes. Las dosis y aplicaciones se distribuyen con reglas configuradas; el servicio puede subdividir según el máximo de N por aplicación.

## Edad y restricciones

Etapas por edad: vivero hasta 8 meses, establecimiento hasta 12, levante hasta 24, producción inicial hasta 48 y estable después. Hasta 3 meses no se emite dosis de campo. De 4 a 24 meses se usa el plan general acumulado de café joven, con cinco momentos de referencia (meses 2, 6, 10, 14 y 18); no repetir aplicaciones ya realizadas. Producción usa cuatro reglas de calendario de configuración.

Se validan superficie/densidad positivas, variedad registrada con factores y coincidencia del cultivo del conjunto activo. La CE puede impedir un plan automático conforme al umbral configurado. Las demás advertencias y condiciones deben conservarse en la interfaz; no convertir apoyo a decisiones en una garantía de rendimiento.

## Evaluación orgánica optativa

`include_organic` es `false` por defecto; Flutter lo activa. El escenario compara Bocashi, Biol y Compost de pulpa de café con el objetivo mineral, sin volver a dividirlo por eficiencia. Los sólidos se corrigen por humedad y composición en base seca; P y K elementales se convierten a óxidos. El biol usa concentraciones por litro, sin densidad ficticia.

Se fija un volumen ilustrativo limitado de biol y se evalúan combinaciones de los dos sólidos con cantidades no negativas y aportes totales acotados por los objetivos de comparación. Se maximiza cobertura relativa y se recalcula el balance con cantidades finales redondeadas hacia abajo. Composición total no equivale a absorción en el ciclo: no se aplica una tasa universal de mineralización.

El escenario orgánico se añade en la rama productiva (más de 24 meses), cuando se solicita; no se añade al retorno de vivero o café joven. Económico y Bajo cloruro no siempre aparecen juntos: CE elevada prioriza solo Bajo cloruro, y la alternativa potásica depende de que haya requerimiento de K₂O.

Los estados `partial` y `reference_only` conservan `can_apply: false`; no generan calendario ejecutable. El contrato impide promoverlos como una aplicación mineral. No implica certificación orgánica.

## Persistencia y compatibilidad

`FertilizationPlan` guarda el snapshot JSON y la versión del motor; `FertilizationPlanItem` mantiene cantidades normalizadas de productos minerales. Los candidatos orgánicos permanecen en JSON, con unidades nativas. No se crearon tablas ni migraciones para esta capacidad.

Las huellas deterministas permiten recuperar planes equivalentes. Sin Orgánico se preserva la forma antigua de la petición para la huella; con Orgánico se incorpora contexto de perfiles/modelo/política. El router filtra la capacidad también en recuperación y caché. Plan guardado no significa aplicación realizada, gasto contabilizado ni tarea fenológica creada.

## Clima y fenología

El servicio climático es independiente. Suma precipitación de los primeros dos días: riesgo 0 hasta 10 mm, (lluvia−10)/40 hasta 50 mm, 1 por encima. Riesgo >0.6 genera alerta para posponer; calor genera alertas desde 37 °C, críticas desde 42 °C. La pérdida potencial mostrada (`riesgo × 50%`) es una heurística del código, no una medición económica ni una predicción validada por finca.

No existe una matriz de infiltración integrada ni un bloqueo automático del cálculo de fertilización por alerta climática. El calendario presenta pronóstico y alertas; las instancias fenológicas se gestionan por API y selección de etapa, sin un modelo implementado de múltiples cohortes de floración.

## Validación y mantenimiento

Backend: pruebas en `backend/tests/`, ejecutadas desde `backend` con `python -m unittest discover -s tests -v` y variables de entorno de prueba. Flutter: `flutter analyze` y `flutter test` desde `app_flutter`. Los datos ficticios no sustituyen ensayo de campo ni infraestructura real.

Los PDF agronómicos del repositorio son referencias de diseño. Rangos de otros nutrientes y formulaciones propuestas no pasan a ser funcionalidades por figurar en esos documentos. Cualquier ampliación debe añadir contratos, cálculo, fuentes verificables y validación antes de documentarse como integrada.
