# Guía de evaluación de Ágrifos

Base documental: `main` en `e28cf2b` (PR #86), 9 de octubre de 2026. La versión del despliegue y del APK se comprueba durante la evaluación; no se presume actualizada por un merge.

Esta guía permite verificar la API desplegada en Azure, probar sus endpoints protegidos e instalar la aplicación Android.

## 1. Verificar el backend en Azure

Ágrifos está desplegado en una VM de Azure con HTTPS válido. Caddy termina HTTPS y dirige el tráfico a Nginx; Nginx conecta con FastAPI. La API y PostgreSQL se ejecutan en contenedores aislados. El monitoreo local comprueba su disponibilidad cada dos minutos.

1. Abra la [portada de Ágrifos API](https://agrifos-api.northcentralus.cloudapp.azure.com/).
2. Espere hasta que la portada indique que el servicio está disponible.
3. Presione **Abrir Swagger UI** para consultar y probar los endpoints.

También puede abrir directamente los recursos técnicos:

- [Swagger UI](https://agrifos-api.northcentralus.cloudapp.azure.com/docs): documentación interactiva.
- [ReDoc](https://agrifos-api.northcentralus.cloudapp.azure.com/redoc): referencia legible de la API.
- [API Health](https://agrifos-api.northcentralus.cloudapp.azure.com/health): disponibilidad y versión del backend.
- [Database Health](https://agrifos-api.northcentralus.cloudapp.azure.com/health/db): conexión y latencia de PostgreSQL.

Una respuesta correcta de `/health` tiene esta estructura:

```json
{
  "status": "healthy",
  "service": "agrifos-api",
  "version": "1.0.0-beta.3",
  "timestamp": "2026-09-04T18:30:00+00:00"
}
```

Una respuesta correcta de `/health/db` tiene esta estructura:

```json
{
  "status": "healthy",
  "database": "postgresql",
  "latency_ms": 42.15,
  "timestamp": "2026-09-04T18:30:00+00:00"
}
```

## 2. Autorización para probar endpoints

Los endpoints de negocio requieren un access token JWT válido emitido por la autenticación nativa de FastAPI (`AUTH_PROVIDER=native`). Los endpoints públicos de registro, login y recuperación se describen en Swagger. La portada, `/health`, `/health/db`, `/docs`, `/redoc` y `/openapi.json` son públicos.

En Swagger UI:

1. Presione **Authorize**.
2. Pegue únicamente el access token en el campo de autenticación Bearer. Swagger agrega automáticamente el prefijo `Bearer`.
3. Presione **Authorize** y cierre el cuadro.
4. Abra un endpoint, seleccione **Try it out**, complete sus parámetros y presione **Execute**.

### Obtener un token de prueba

Utilice una cuenta confirmada y las credenciales proporcionadas por el equipo por un canal privado. En Swagger, abra `POST /auth/login` y envíe:

```json
{
  "email": "<CORREO_DE_PRUEBA>",
  "password": "<CONTRASEÑA_DE_PRUEBA>"
}
```

Si la cuenta no tiene MFA activo, la respuesta contiene `access_token`, `token_type` y `expires_in`. Si tiene MFA, la respuesta contiene `mfa_required: true`, `challenge_id` y `expires_in`; todavía no hay una sesión autorizada. Abra `POST /auth/mfa/verify` y envíe:

```json
{
  "challenge_id": "<CHALLENGE_ID_DEL_LOGIN>",
  "code": "<CODIGO_TOTP_DE_6_DIGITOS>"
}
```

Copie el `access_token` devuelto y complete **Authorize**. Conserve el código como texto para mantener ceros iniciales. Los JWT y los desafíos expiran: ante `401`, repita el login y, si corresponde, la verificación TOTP. No use un token de Supabase para esta entrega.

Para registrar una cuenta, use la app o `POST /auth/register` con `name`, `email` y `password`, y complete la confirmación de correo. El registro no emite un token de sesión. Confirmación y recuperación dependen de la configuración SMTP del servidor; si no llega el correo, compruebe esa integración antes de considerar validado el flujo. Credenciales, contraseñas, tokens y secretos TOTP no deben publicarse en el repositorio ni en capturas.

## 3. Roles disponibles

| Rol | Alcance |
|---|---|
| `farmer` | Rol predeterminado. Puede administrar sus propias fincas, parcelas, lecturas, análisis y etapas, pero no los registros de otros agricultores. |
| `auditor` | Acceso global de solo lectura. Puede consultar información de distintos agricultores, pero las operaciones de escritura responden `403`. |
| `admin` | Acceso global de lectura y escritura. También puede administrar usuarios, cultivos, variedades y plantillas fenológicas. |

Para evaluar el flujo completo, se recomienda crear una cuenta nueva desde la aplicación. Toda cuenta recién registrada recibe automáticamente el rol `farmer`, por lo que el evaluador podrá registrar sus propias fincas y parcelas, completar el resto del recorrido y probar en la API las operaciones `POST`, `PUT`, `PATCH` y `DELETE` con sus propios datos.

Si el equipo proporciona una cuenta `auditor`, está destinada a comprobar el acceso global de solo lectura. Permite consultar datos mediante operaciones `GET`, pero no crear ni modificar registros: las solicitudes `POST`, `PUT`, `PATCH` y `DELETE` deben responder HTTP `403`.

Los roles `auditor` y `admin` deben asignarse previamente por un administrador; el usuario no puede elevar su propio rol desde la aplicación.

Para confirmar la identidad y el rol de la cuenta autorizada, ejecute:

```http
GET /users/me
```

## 4. Recorrido sugerido por la API

Con una cuenta `farmer` autorizada:

1. `GET /users/me` — comprobar identidad y rol.
2. `GET /crops` y `GET /varieties` — consultar los catálogos agronómicos.
3. `POST /farms` — registrar una finca.
4. `POST /parcels` — registrar una parcela asociada a la finca.
5. `GET /phenological-stages/templates` — consultar las etapas disponibles para el cultivo.
6. `POST /phenological-stages/instances` — registrar una etapa en la parcela.
7. `POST /readings` — guardar una lectura del sensor y recibir su diagnóstico inmediato.
8. `GET /diagnostics/readings/{reading_id}` — consultar nuevamente el diagnóstico.
9. `POST /lab-analyses` — registrar un análisis de laboratorio.
10. `POST /fertilization/recommendations` — generar o recuperar una recomendación para los datos registrados.
11. `GET /fertilization/plans/latest?parcel_id={parcel_id}` — consultar el último plan guardado sin crear uno nuevo.
12. `GET /weather/farms/{farm_id}/forecast` — consultar el pronóstico de la finca.
13. `POST /alerts/farms/{farm_id}/evaluate` — evaluar el pronóstico y sincronizar las alertas climáticas.

Para comprobar los permisos, una cuenta `auditor` puede repetir consultas `GET`; cualquier intento de crear, editar o eliminar información debe responder HTTP `403`.

## 5. Instalar y probar el APK

1. Obtenga el APK de release de esta entrega del equipo o de [GitHub Releases de Ágrifos](https://github.com/ferjovel06/agrifos/releases), si ya fue publicado.
2. Confirme que ese APK se compiló para la API de Azure y autenticación `native`. La última prerelease publicada al revisar esta guía es de septiembre de 2026; no presuponga que contiene la actualización de Azure.
3. En el dispositivo Android, permita temporalmente la instalación desde la aplicación usada para descargar el archivo.
4. Instale el APK y abra Ágrifos.
5. Cree una cuenta nueva para probar el flujo completo como `farmer`, o inicie sesión con la cuenta `auditor` proporcionada si solo desea comprobar las consultas de lectura.

Para compilar el APK desde el proyecto, configure `app_flutter/.env` con valores públicos y `app_flutter/android/key.properties` con el keystore de release. Desde `app_flutter/`:

```bash
flutter pub get
flutter build apk --release --target-platform android-arm64 --dart-define=AUTH_PROVIDER=native --dart-define=API_BASE_URL=https://agrifos-api.northcentralus.cloudapp.azure.com
```

El resultado está en `app_flutter/build/app/outputs/flutter-apk/app-release.apk`. Este comando está dirigido a dispositivos ARM64; ajuste la arquitectura para otros dispositivos. Mantenga el mismo keystore para actualizar una instalación existente. La copia instalada durante las pruebas usa firma de desarrollo para preservar los datos; para la entrega final pruebe el APK con firma de release en un dispositivo compatible. Android rechaza actualizar una app con una firma distinta.

Recorrido móvil sugerido:

- Inicio y cierre de sesión.
- Confirmación de correo y recuperación de contraseña.
- Consulta y edición del perfil.
- Activación y verificación de MFA mediante TOTP.
- Selección, registro y edición de fincas y parcelas.
- Selección de cultivo, variedad y etapa fenológica.
- Captura manual de análisis de laboratorio.
- Consulta del diagnóstico y del plan de fertilización completo.
- Consulta del pronóstico y las alertas climáticas.
- Conexión del sensor de suelo genérico 7 en 1 mediante USB OTG, si el hardware está disponible.

## 6. Consideraciones para la evaluación

- Se necesita conexión a internet para acceder a la API de Azure. La app no se conecta directamente a PostgreSQL; lo hace FastAPI.
- CORS no restringe al cliente Android/iOS nativo. Si se añade un cliente web, configure sus orígenes por separado.
- Los secretos de JWT, MFA, PostgreSQL y SMTP permanecen en el servidor; el `.env` empaquetado en el APK solo contiene configuración pública.
- Compruebe sin conexión que la app muestra mensajes amigables y permite reintentar; al vencer la sesión, debe volver al login.
- El sensor físico es opcional para revisar el resto del flujo; los análisis de laboratorio pueden ingresarse manualmente.
- Las credenciales de evaluación son temporales y deben utilizarse únicamente para revisar esta entrega.

## 7. Verificar las capacidades fusionadas

- Comparar `/health` y `/openapi.json` con la compilación evaluada. `1.0.0-beta.3` es la versión declarada en esta base; no identifica por sí sola el commit desplegado.
- Solicitar Orgánico con `include_organic: true` en POST y en GET del último plan. Comprobar el orden Económico/Bajo cloruro/Orgánico cuando corresponda, unidades kg y L, balance parcial y ausencia de aplicaciones ejecutables. Sin esa capacidad, verificar la respuesta compatible anterior.
- Abrir Finanzas y registrar/editar/eliminar ingresos y egresos de prueba; consultar `/finances/dashboard?farm_id={farm_id}`. Comprobar balance y margen con importes conocidos, y valores nulos cuando no hay base para calcular porcentajes.
- Confirmar que Ca/Mg/S del laboratorio no se presentan como dosis complementarias calculadas. La base fusionada mantiene el balance productivo NPK.
- Verificar con otra cuenta que no puede consultar o modificar fincas ajenas salvo permisos globales de lectura aplicables. Mantener los casos de auditor sin escritura.

Una demo con fixtures no valida conexión real a Azure o a los proveedores de clima, envío de correo, captura de sensor físico ni eficacia agronómica.
