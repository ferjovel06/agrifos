# Ágrifos: implementación del escenario Orgánico

Fecha de implementación: 6 de octubre de 2026. Preparación de entrega: 8 de octubre de 2026. Rama: `feat/organic-fertilization`.

Estado actual: integrado en `main` mediante PR #74, commit `f986ccb`. Los apartados de ubicación y validación siguientes conservan el historial de implementación local; sus rutas D son específicas de ese entorno. No describen una ejecución nueva de pruebas durante esta actualización documental.

## Base y ubicación

Se clonó `https://github.com/ferjovel06/agrifos.git` en `D:\Agrifos\agrifos-organico-local` desde la rama predeterminada. Base: `c46a14f6ff8687803efebfcb20099df57db2410e`, merge del PR 72 del tablero financiero.

El trabajo, Python de pruebas, dependencias descargadas, cachés, temporales, registros y demo están en D. No se cambiaron las otras copias del repositorio. Se leyó el runtime Python existente en C para copiarlo a D; las instalaciones y ejecuciones de este trabajo usan la copia en D.

## Qué está implementado

- Capacidad optativa `include_organic` en POST de recomendaciones y GET de último plan. Por defecto permanece desactivada para consumidores anteriores; la aplicación Flutter actualizada la solicita.
- Tercer escenario **Orgánico**, después de Económico/Bajo cloruro, con **Bocashi → Biol → Compost de pulpa de café**.
- Perfiles bibliográficos versionados, con humedad de sólidos, conversión elemental a óxidos y concentraciones líquidas en kg de nutriente/L.
- Cantidades nativas y conversiones a manzana/planta: kg/g para sólidos y L/mL para biol. No se asume densidad de 1 kg/L.
- Evaluación con cantidades no negativas y topes totales de N/P/K iguales a los objetivos comparados. Se examinan vértices del problema de dos sólidos después de fijar un volumen ilustrativo de biol hasta 100 L/ha, reducido si un objetivo lo limita. Se maximiza la suma de coberturas relativas restantes.
- Balance agregado desde las cantidades finales redondeadas hacia abajo: aportes, faltantes y excedentes. No es un optimizador de dosis de campo, ni una búsqueda comercial de costo mínimo.
- Estados `partial` y `reference_only`, ambos sin aplicaciones ejecutables. El contrato rechaza promoverlos con `can_apply=true` o dosis minerales aplicables.
- Snapshot JSON conserva los candidatos orgánicos. No entran al catálogo ni a las filas normalizadas en kg del plan mineral.
- Filtrado por capacidad también en GET y respuestas de caché. El formato de entrada para la huella antigua se preserva cuando no se solicita Orgánico; la nueva huella incluye perfiles, modelo y política.
- Flutter muestra objetivos minerales para comparación, cantidades etiquetadas como referencia, balance y disponibilidad desconocida. Aplicaciones explica que falta validación. Los avisos propios del escenario sustituyen en esa vista a instrucciones generales de aplicar fertilizantes minerales.

Los métodos minerales, ramas de vivero/levante, migraciones, calendario fenológico y módulo financiero existentes se conservan. No se insertan tareas ni gastos de una evaluación no aprobada.

## Resultado del caso de referencia

Objetivos: N 71.07, P₂O₅ 20.20 y K₂O 15.73 kg/ha. Las eficiencias ya están incluidas; no se vuelven a dividir.

| Fuente | Cantidad de evaluación/ha |
|---|---:|
| Bocashi | 1,372.18 kg |
| Biol | 100 L de concentrado |
| Compost de pulpa | 472.65 kg |

Aporte total: N **16.5996**, P₂O₅ **20.1999**, K₂O **15.7299** kg/ha. Faltante N de comparación: **54.4704 kg/ha**. Estado parcial, sin calendario ejecutable. El redondeo explica las diferencias mínimas con el documento matemático anterior.

Los 100 L son una variable ilustrativa, no una dosis aprobada. Los topes son restricciones de comparación, no umbrales toxicológicos. Los perfiles varían entre recetas y lotes; estos resultados no se generalizan a cualquier abono de esas categorías. La disponibilidad temporal permanece desconocida.

## Archivos principales

| Capa | Archivos |
|---|---|
| Motor orgánico | `backend/app/services/organic_fertilization.py` |
| Integración | `backend/app/services/fertilization_service.py` |
| Contratos | `backend/app/schemas/fertilization.py` |
| API y huellas | `backend/app/routers/fertilization.py` |
| Persistencia | `backend/app/repositories/fertilization_plan.py` |
| Cliente | `app_flutter/lib/data/api/fertilization_repository.dart` |
| Entidades | `app_flutter/lib/domain/entities/fertilization_recommendation.dart` |
| Pantalla | `app_flutter/lib/presentation/fertilization/fertilization_plan_screen.dart` |
| Pruebas nuevas | `backend/tests/test_organic_fertilization*.py`, `app_flutter/test/presentation/fertilization/organic_fertilization_test.dart` |
| Fixture entre capas | `app_flutter/test/fixtures/organic_recommendation.json` |
| Demo reproducible | `backend/tools/generate_organic_demo.py`, `app_flutter/tool/organic_demo.dart` |

Para esta fase se utiliza un DTO de candidatos con unidad nativa explícita, separado de `ProductDoseRead`. Se evita añadir un calendario líquido vacío complejo antes de tener aplicaciones aprobadas. La futura fase agronómica deberá definir contratos de calendario líquido, agua/dilución y validación por lote; no se simula que eso ya existe.

## Validación realizada

- **Backend: 116 pruebas satisfactorias**, batería completa de `unittest discover -s tests`.
- **Flutter: 83 pruebas satisfactorias**, incluidas las pruebas del selector, lectura del fixture real y bloqueo de aplicaciones. El ajuste final de pantalla también pasó sus pruebas específicas.
- `flutter analyze`: sin problemas.
- Compilación Python: satisfactoria.
- Alembic: una cabeza, `b2c4d6e8f901`; no se añadió ni ejecutó migración.
- Demo web compilada usando los widgets de la aplicación y una respuesta generada por el servicio real.
- Prueba HTTP con rutas FastAPI reales y dobles de autenticación/repositorio: POST, snapshot, GET, respuesta de caché y filtrado del escenario para clientes anteriores.
- Persistencia probada con sesión aislada: candidatos en snapshot y ausencia de filas orgánicas en kg.

Los mensajes de fallas de salud/clima/autenticación presentes en los registros corresponden a casos negativos intencionales de las pruebas. Las dependencias nuevas emiten avisos de deprecación de TestClient/HTTP 422; la batería finaliza satisfactoriamente.

## Emulación local y límites

La plataforma web no está configurada en el repositorio actual. Para evitar añadir una plataforma entera a la aplicación, se creó `D:\Agrifos\organic-preview-web` con dependencia local a `app_flutter`. Su `main.dart` usa la pantalla real y los datos de `tool/organic_demo.dart`.

En la validación histórica, la demo se sirvió en **http://127.0.0.1:8876/**. Se revisó el selector, el resumen y Aplicaciones con un viewport móvil de 390 × 844. Es una emulación visual en navegador, **no una ejecución en un emulador Android ni una prueba de Bluetooth/OTG**.

No se conectó a Supabase remoto, no se escribieron datos productivos y no se validó un ciclo real contra PostgreSQL. Esas integraciones no se declaran probadas. La demo utiliza parcela e identificadores ficticios y densidad de 5,000 plantas/ha; no afirma que esa densidad sea la de la captura del usuario.

Python local: 3.12; Flutter instalado en D: 3.47.5 / Dart 3.13.4. CI del repositorio usa Python 3.13 y Flutter 3.44.9. La validación local no sustituye una ejecución futura de ese CI. `flutter pub get` ajustó cuatro dependencias transitivas del SDK en el entorno de prueba; el lock original se conserva en la propuesta para no introducir un cambio ajeno de dependencias.

El compilador de la demo informa una advertencia sobre la familia opcional CupertinoIcons; la pantalla utiliza MaterialIcons y se verificó su representación. La compilación fue satisfactoria.

## Cómo repetir las comprobaciones en D

Preparar PowerShell:

```powershell
$env:TEMP = 'D:\Agrifos\local-organico-runtime\tmp'
$env:TMP = $env:TEMP
$env:PUB_CACHE = 'D:\Agrifos\local-organico-runtime\pub-cache'
$env:APPDATA = 'D:\Agrifos\local-organico-runtime\appdata'
$env:LOCALAPPDATA = 'D:\Agrifos\local-organico-runtime\localappdata'
$env:GRADLE_USER_HOME = 'D:\Agrifos\local-organico-runtime\gradle'
$env:ANDROID_USER_HOME = 'D:\Agrifos\local-organico-runtime\android-user'
$env:CI = 'true'
$env:DATABASE_URL = 'postgresql+asyncpg://local:local@127.0.0.1:5432/agrifos_local'
$env:SUPABASE_URL = 'http://127.0.0.1:54321'
```

Backend:

```powershell
Set-Location D:\Agrifos\agrifos-organico-local\backend
& D:\Agrifos\local-organico-runtime\python\python.exe -m unittest discover -s tests -q
& D:\Agrifos\local-organico-runtime\python\python.exe -m compileall -q app tools tests
$env:PYTHONPATH = (Get-Location).Path
& D:\Agrifos\local-organico-runtime\python\python.exe tools/generate_organic_demo.py
```

Flutter en el entorno ya resuelto:

```powershell
Set-Location D:\Agrifos\agrifos-organico-local\app_flutter
& D:\flutter\bin\flutter.bat analyze --no-pub
& D:\flutter\bin\flutter.bat test --no-pub
```

En una instalación nueva, crear `.env` desde `.env.example` y resolver dependencias con el SDK correspondiente. El SDK local más nuevo vuelve a ajustar dependencias transitivas al ejecutar `pub get`; revisar ese diff por separado antes de proponer un commit.

Demo:

```powershell
Copy-Item D:\Agrifos\agrifos-organico-local\app_flutter\tool\organic_demo.dart D:\Agrifos\organic-preview-web\lib\main.dart
Set-Location D:\Agrifos\organic-preview-web
& D:\flutter\bin\flutter.bat build web --no-pub --no-web-resources-cdn
& D:\Agrifos\local-organico-runtime\python\python.exe -m http.server 8876 --bind 127.0.0.1 --directory build/web
```

Registros: `D:\Agrifos\local-organico-runtime\backend-tests.log` y `flutter-tests.log`. Capturas: `D:\Agrifos\local-organico-runtime\capturas`.

## Estado de entrega y validación pendiente

El escenario de evaluación está fusionado en main mediante PR #74. Mantiene el resultado parcial visible y las aplicaciones deshabilitadas. Para convertirlo en receta ejecutable faltan lotes analizados, equivalencias/disponibilidad validadas, vías, límites y calendarios aprobados, además de pruebas de integración con la infraestructura elegida.

La validación local previa se realizó sin commit, push, despliegue ni migración de datos. La entrega se realizó en commits separados: backend `5146aa3` y frontend `915dde8`, posteriormente fusionados por `f986ccb`.

## Revisión visual y comprobación del bocashi, 6 de octubre

Las fuentes orgánicas reutilizan ahora `_ProductCard`, el mismo componente que Económico y Bajo cloruro: ícono verde, nombre y conversiones a la izquierda; cantidad azul y unidad por hectárea a la derecha. El encabezado muestra «Fuentes y dosis totales · evaluación de referencia». Las tres fuentes aparecen primero; el aviso de evaluación y el balance se presentan debajo. No se etiqueta el análisis bibliográfico como grado garantizado.

Para bocashi se mantiene la cantidad exacta en kg/ha y se añade su equivalencia redondeada en toneladas. El biol conserva L/ha, L/manzana y mL/planta.

Se recalculó con aritmética decimal independiente del motor:

```text
Cantidad recibida: 1372.18 kg/ha = 1.37218 t/ha
Materia seca: 1372.18 × (1 − 0.41) = 809.5862 kg/ha
N total: 809.5862 × 0.0131 = 10.60557922 kg/ha
P2O5 total: 809.5862 × 0.0104 × 2.291 = 19.28952463568 kg/ha
K2O total: 809.5862 × 0.0097 × 1.205 = 9.46284829870 kg/ha
Manzana: 1372.18 × 0.7042 = 966.289156 kg/mz
Por planta, con la densidad ficticia de la demo:
1372.18 × 1000 / 5000 = 274.436 g/planta
```

La composición se volvió a contrastar con [Cenicafé, tabla 5 y explicación de base seca](https://publicaciones.cenicafe.org/index.php/libros_manuales/article/download/3239/3274). No se detectó error de conversión entre kg y toneladas. El orden de magnitud responde a la concentración del material: cada tonelada recibida aporta solo 7.729 kg de N total con ese perfil. El balance completo continúa siendo parcial; no se interpreta la cantidad como dosis aprobada.

La prueba visual automatizada se ajustó a 390 × 844. Detectó y permitió corregir desbordes de las insignias de nutrientes y el título de los avisos. Tras el ajuste, la batería completa de Flutter vuelve a pasar sus 83 pruebas y el análisis estático no informa problemas. Registro: `D:\Agrifos\local-organico-runtime\flutter-tarjetas-tests.log`.

## Actualización de la base y entrega, 8 de octubre

Se integró origin/main hasta a1df7e0 (PR 73, ejecutor local de pruebas del backend) sin conflictos. Tras actualizar, pasaron las 116 pruebas del backend y la compilación web. La validación previa de Flutter pasó 83 pruebas y el análisis estático no informó problemas. La vista local usa datos de ejemplo; no sustituye una prueba de infraestructura real ni valida dosis agronómicas.
