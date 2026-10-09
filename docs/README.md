# Documentación de Ágrifos

Base `origin/main` (`8182f9f`); propuesta offline-first en rama independiente, octubre de 2026. No implica despliegue ni merge.

| Documento | Uso |
|---|---|
| [README del proyecto](../README.md) | Presentación, configuración y ejecución |
| [Offline-first](offline-first.md) | Alcance, sincronización, seguridad y uso |
| [Refactorización offline](offline-refactor.md) | Auditoría, métricas y simplificaciones aplicadas |
| [Validación offline](offline-validation.md) | Pruebas reales y pendientes |
| [Auditoría USB](sensor-audit.md) | Ruta original y matriz de información física faltante |
| [Mediciones trazables](sensor-measurements.md) | Contrato, adquisición, calidad, procesamiento y reprocesamiento |
| [Campaña de calibración](sensor-calibration-plan.md) | Muestreo, comparabilidad, validación y aceptación física |
| [Validación NPK](sensor-validation.md) | PASS/FAIL/NOT RUN, evidencia, resultados y entrega dependiente |
| [Estado implementado](ESTADO_IMPLEMENTADO.md) | Capacidades, límites y fuentes de verdad |
| [Motor](agrifos_engine_documentation.md) | Contrato, cálculo, unidades y persistencia |
| [Guía de evaluación](guia_evaluador.md) | Recorrido API y aplicación |
| [Arquitectura](diagrams/architecture_diagram.mmd) | Componentes y conexiones implementadas |
| [Actividad](diagrams/activity_diagram.mmd) | Generación y recuperación de planes |
| [Clases](diagrams/class_diagram.mmd) | Clases SQLAlchemy persistidas |
| [ER](diagrams/er_diagrams/agrifos_er_diagram.mmd) | Tablas, atributos y relaciones |

Las vistas ER por módulo están en `diagrams/er_diagrams/`. Sus campos se derivan de los modelos actuales, incluyendo nulabilidad de relaciones y tipos monetarios. Los Mermaid son la referencia mantenida. Los PNG/SVG anteriores corresponden al diseño previo; no se regeneraron como si fueran vistas del código vigente.

Los PDF `coffee_phenology_and_fertilization_engine.pdf` y `coffee_soil_laboratory_parameters.pdf` conservan su carácter de referencia agronómica de diseño. Algunas propuestas exceden lo integrado; consultar el estado implementado antes de utilizarlas como especificación de comportamiento.
