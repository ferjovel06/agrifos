# Documentación de Ágrifos

Revisión sincronizada con `main` (`f986ccb`, PR #74), 8 de octubre de 2026.

| Documento | Uso |
|---|---|
| [README del proyecto](../README.md) | Presentación, configuración y ejecución |
| [Estado implementado](ESTADO_IMPLEMENTADO.md) | Capacidades, límites y fuentes de verdad |
| [Motor](agrifos_engine_documentation.md) | Contrato, cálculo, unidades y persistencia |
| [Guía de evaluación](guia_evaluador.md) | Recorrido API y aplicación |
| [Arquitectura](diagrams/architecture_diagram.mmd) | Componentes y conexiones implementadas |
| [Actividad](diagrams/activity_diagram.mmd) | Generación y recuperación de planes |
| [Clases](diagrams/class_diagram.mmd) | Clases SQLAlchemy persistidas |
| [ER](diagrams/er_diagrams/agrifos_er_diagram.mmd) | Tablas, atributos y relaciones |

Las vistas ER por módulo están en `diagrams/er_diagrams/`. Sus campos se derivan de los modelos actuales, incluyendo nulabilidad de relaciones y tipos monetarios. Los Mermaid son la referencia mantenida. Los PNG/SVG anteriores corresponden al diseño previo; no se regeneraron como si fueran vistas del código vigente.

Los PDF `coffee_phenology_and_fertilization_engine.pdf` y `coffee_soil_laboratory_parameters.pdf` conservan su carácter de referencia agronómica de diseño. Algunas propuestas exceden lo integrado; consultar el estado implementado antes de utilizarlas como especificación de comportamiento.
