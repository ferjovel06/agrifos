# Bloqueantes de Docker: diagnóstico y propuesta pendiente de aprobación

Fecha: 2026-10-08. Rama: `chore/docker-environment`.
Código analizado: `857b897dbb7e7ad771a6c2831090c8a5a7ecbeb2`.
**La dockerización sigue INCOMPLETA y no está aprobada para integrar en main.**
Esta fase incorpora solamente este informe y evidencia local de diagnóstico.
No aplica cambios de arquitectura, arranque, dependencias, Docker Desktop ni licencias.

## 1. Diagnóstico de publicación de puertos

Entorno comprobado: Docker Desktop 4.55.0, Engine 29.1.3, contenedores Linux amd64
sobre Windows/WSL2 y Supabase CLI autónoma 2.120.0.
La red propia `agrifos-it-41e1be45` conserva
`com.docker.network.bridge.host_binding_ipv4=127.0.0.1`.
El driver de integración anterior falló durante el arranque de Mailpit, antes de
migraciones de Agrifos, Auth, MFA y persistencia.

En esta fase se repitió la publicación con procesos Python que únicamente duermen,
sin servidores ni sockets de aplicación, sin volúmenes y con limpieza de sus
contenedores identificados por nombre único y etiqueta propia:

| Publicación nativa | HostConfig solicitado | Binding resuelto por Docker | Resultado de restricción |
|---|---|---|---|
| `-p 0:8080` en el bridge propio | HostIp vacío | `0.0.0.0:32769` y `[::]:32769` | FAIL |
| `-p 127.0.0.1:0:8080` en el mismo bridge | HostIp `127.0.0.1` | `127.0.0.1:32770`, sin wildcard IPv6 | PASS |

Los contenedores de diagnóstico fueron retirados. Los puertos son efímeros;
no deben copiarse como configuración. Esto prueba el comportamiento de bindings,
no una prueba completa de conectividad ni aislamiento desde otra máquina.
Evidencia: `.docker/evidence/network-blockers-diagnosis.json`.

La [documentación de Docker](https://docs.docker.com/engine/network/port-publishing/)
y la [guía local de Supabase](https://supabase.com/docs/guides/local-development)
recomiendan precisamente ese bridge para publicaciones sin IP. En este entorno
la opción no determina el binding observado. El fallo también ocurre sin Supabase:
no se explica solamente por el parser TOML o por un servicio Mailpit defectuoso.

El [constructor de argumentos del CLI 2.120.0](https://github.com/supabase/cli/blob/v2.120.0/apps/cli/src/command-internal/db-bootstrap/docker-create-args.ts)
genera publicaciones `hostPort:containerPort`, sin HostIp.
[Kong](https://github.com/supabase/cli/blob/v2.120.0/apps/cli/src/commands/start/services/kong.service.ts),
[Mailpit](https://github.com/supabase/cli/blob/v2.120.0/apps/cli/src/commands/start/services/mailpit.service.ts)
y Studio usan esa ruta. `start --help` no ofrece un flag de binding.
`SUPABASE_SERVICES_HOSTNAME` cambia URLs, no esas publicaciones.
Cambiar únicamente Mailpit o el hostname no corrige todas las rutas.

Docker Desktop incorporó una política global de puertos en 4.52.0.
Las notas de 4.38.0 documentan una discrepancia GUI/CLI que forzaba HostIp wildcard;
las de 4.88.0 documentan una corrección de lo mostrado por `docker ps` bajo políticas
localhost. Son antecedentes, **no prueba de una versión que resuelva nuestro caso**.
No encontré una incidencia oficial que permita atribuir con certeza este fallo
concreto al Engine o al forwarding de Desktop, ni garantizar una actualización.
No se debe interpretar un binding wildcard como seguro por una posible discrepancia
de representación. [Notas oficiales](https://docs.docker.com/desktop/release-notes/).

### Alternativas comparadas

| Alternativa | Reproducibilidad y alcance | Riesgos / coste | Evaluación |
|---|---|---|---|
| Bridge loopback + CLI oficial actual | Es el flujo actual y está documentado oficialmente | Falla la sonda en este Desktop; Linux host sigue sin prueba real | Conservar como diagnóstico; no desbloquea Windows |
| Política Desktop “Localhost only” o “Localhost by default” | Mantiene CLI y topología; en Linux Engine se conserva el bridge | Configuración global: afecta proyectos ajenos y puede requerir reinicio; la inspección de versiones antiguas puede seguir mostrando wildcard | Menor cambio de código, pero requiere autorización independiente y prueba; no aplicarla automáticamente |
| Publicación explícita mediante adaptador local del ejecutable Docker | Mismo CLI 2.120.0, servicios y única red; regla idéntica en Windows/Linux | Código de mediación propio; validar exhaustivamente argumentos, PATH, señales, errores y cada creación del CLI | **Recomendación para una solución reproducible por proyecto** |
| Parche/recompilación del CLI fijado | Añadir IP a su constructor común evita la mediación de argumentos | Mantener un fork, su toolchain Bun/pnpm y sus binarios por plataforma; mayor carga de actualización | Viable, más mantenimiento que un adaptador pequeño |
| Compose para el subconjunto Supabase necesario | IP explícita en cada publicación; flujo Docker nativo en ambas plataformas | Cambia mecanismo de arranque y propiedad del bootstrap; mantener SQL inicial, roles, claves, Kong, salud y migraciones de Auth; no usar el stack self-hosted completo sin necesidad | Alternativa si se rechaza la mediación; cambio mayor |
| Actualizar Desktop/CLI o cambiar a otro Engine | Podría recuperar el comportamiento oficial | Cambio del host o versiones, sin corrección concreta acreditada; Linux alternativo no resuelve todos los Windows declarados | No recomendar como arreglo garantizado |

Las opciones de política y su clave `portBindingBehavior` están en la
[referencia oficial de Docker](https://docs.docker.com/desktop/enterprise/hardened-desktop/settings-management/settings-reference/#port-binding-behavior).
El flujo Compose alternativo se basaría en el
[self-hosting oficial de Supabase](https://supabase.com/docs/guides/self-hosting/docker),
adaptado y reducido; no equivale automáticamente al entorno de la CLI.
No se propone firewall global, red host, proxy, socket Docker en servicios,
publicación wildcard seguida de recreación ni desactivar preflight.

### N1: propuesta concreta recomendada, todavía no implementada

Mantener el binario oficial 2.120.0 y todos los servicios/puertos actuales.
Introducir un adaptador nativo pequeño, con fuente versionada, que invoque el Docker
real por ruta absoluta. El CLI lanza `docker` como proceso hijo:
[código de invocación](https://github.com/supabase/cli/blob/v2.120.0/apps/cli/src/command-internal/container-cli.ts).
Un PATH limitado al proceso Supabase seleccionaría el adaptador, sin modificar el
PATH del usuario, la instalación del CLI ni la configuración global.

1. Generar binarios Windows x64/Linux x86_64 desde fuente propia mediante un builder
   Go fijado por versión/digest en Docker, sin instalar Go en el host ni añadir un
   servicio permanente. Fuente, receta y hashes quedarían auditables.
2. Transformar únicamente publicaciones del proyecto/red propios a
   `127.0.0.1:hostPort:containerPort` antes de crear el contenedor. Preservar
   protocolo, argumentos separados, entorno y códigos de salida.
3. Rechazar publicaciones explícitas fuera de loopback, formatos desconocidos,
   `--publish-all` y red host. Comprobar propiedad y bindings solicitados antes
   de cada `start`; no limitarse a corregir un contenedor después de arrancarlo.
4. Conservar el preflight fail-closed y ejecutarlo a través del mecanismo real
   usado por el CLI. Debe seguir comprobando todos los bindings resueltos y
   rechazar cualquier IP que no sea loopback. La sonda nativa sin adaptador se
   conserva como evidencia del fallo del host.
5. Verificar que todas las rutas de creación del CLI fijado pasan por el adaptador
   en ambas plataformas. Si una ruta lo evita, no arrancar servicios y revisar
   la propuesta antes de continuar. No habilitar fallback a un runtime diferente.

Esto cambia el **mecanismo de lanzamiento**, por lo que necesita aprobación.
La prueba nativa acredita la viabilidad de HostIp explícito; el adaptador completo
y su compatibilidad Windows/Linux están **NOT RUN**.
Debe cubrir DB/bootstrap, Kong, Mailpit, Studio opcional, reinicio y limpieza,
incluidos fallos, señales, rutas con espacios y ausencia de datos sensibles en logs.

## 2. Inventario y aplicabilidad de Trivy

Se analizó el informe real conservado, no se ejecutó ni simuló un escaneo corregido:
`.docker/evidence/scanners/trivy-runtime.json`, generado 2026-10-08 17:15:41 UTC,
Trivy 0.75.0. **FAIL: 60 HIGH + 3 CRITICAL = 63 entradas, 23 CVE distintos.**
Debian aporta 55 entradas (53 HIGH/2 CRITICAL); el lock de aplicación aporta
8 (7 HIGH/1 CRITICAL). Un mismo CVE puede repetirse en varios paquetes binarios.
Estos recuentos no incluyen un inventario de vulnerabilidades MEDIUM/LOW.

Imagen runtime inspeccionada/exportada:
`sha256:d306c20ce70be7ecc3186a04d788a06116ab5ae62103bf91636a86c1fd0e0137`.
Config de plataforma que Trivy identifica:
`sha256:6d8c2cb5ba34ef6c4a02e3b1d909df74f75126d252f6b4f48d84e55b4462ff10`.
Son identificadores de objetos distintos; su correspondencia está registrada en
`.docker/evidence/scanners/runtime-identity.json`.

### Dependencias Python: ocho hallazgos

Las versiones corregidas se contrastaron con los advisories de los mantenedores
y metadata de los wheels oficiales de PyPI; se verificaron sus SHA256 sin instalar.
La aplicabilidad siguiente combina esas condiciones con la inspección de Agrifos.
Una inferencia de alcance reducido no elimina el hallazgo del gate.

| CVE / severidad | Paquete instalado → primera versión corregida | Condición e impacto en Agrifos |
|---|---|---|
| [CVE-2026-102266](https://github.com/jpadilla/pyjwt/security/advisories/GHSA-9j54-fg26-wv3r) HIGH | PyJWT 2.13.0 → 2.14.0 | JWK HMAC vacío. La ruta Agrifos permite solo ES256 y entrega una clave EC; no se observó la precondición HMAC. |
| [CVE-2026-102267](https://github.com/jpadilla/pyjwt/security/advisories/GHSA-9v7f-9g4p-ffgj) HIGH | PyJWT 2.13.0 → 2.14.0 | PyJWKClient confía en redirecciones del JWKS. Relevante a la ruta real; exige influencia sobre la respuesta del endpoint configurado. Diagnóstico local descrito debajo. |
| [CVE-2026-102268](https://github.com/jpadilla/pyjwt/security/advisories/GHSA-ffc3-869f-jxw9) CRITICAL | PyJWT 2.13.0 → 2.14.0 | PEM alterado aceptado como secreto HMAC con algoritmos mezclados. Allowlist exclusivamente ES256 evita esta precondición. |
| [CVE-2026-102271](https://github.com/jpadilla/pyjwt/security/advisories/GHSA-p4g4-x82p-q773) HIGH | PyJWT 2.13.0 → 2.14.0 | Clave pública DER usada como secreto HMAC. No hay verificación HMAC ni clave DER cruda en esta ruta. |
| [CVE-2026-102272](https://github.com/jpadilla/pyjwt/security/advisories/GHSA-r6x4-923q-g947) HIGH | PyJWT 2.13.0 → 2.14.0 | JWK con BOM elude detección HMAC en configuración mixta. Agrifos no permite HS* ni usa ese JSON como secreto. |
| [CVE-2026-102273](https://github.com/jpadilla/pyjwt/security/advisories/GHSA-w2cx-738m-mc7w) HIGH | PyJWT 2.13.0 → 2.14.0 | Contenedor JWK/JWKS público aceptado como HMAC. Misma precondición mixta, ausente en el verificador inspeccionado. |
| [CVE-2026-97687](https://github.com/urllib3/urllib3/security/advisories/GHSA-8988-9cw3-xx77) HIGH | urllib3 2.7.0 → 2.8.0 | Política TLS de proxy HTTPS sustituida por la del destino. No se encontró ProxyManager ni Sentry inicializado en app; dependiente del uso futuro de Sentry/proxy. |
| [CVE-2026-97689](https://github.com/urllib3/urllib3/security/advisories/GHSA-vxq7-64xx-v4gw) HIGH | urllib3 2.7.0 → 2.8.0 | Respuesta chunked maliciosa agota memoria al leer tamaño de chunk. Requiere stream/read_chunked; no se encontró ese uso en app. El paquete permanece instalado. |

El backend usa `PyJWKClient` con urllib de la biblioteca estándar, **no urllib3**.
Las llamadas meteorológicas usan HTTPX. La cadena de urllib3 en el lock es:
`fastapi[standard] → fastapi-cli[standard] → fastapi-cloud-cli → sentry-sdk 2.66.1 → urllib3`.
Sentry exige `urllib3>=1.26.11`, compatible con 2.8.0.

Para CVE-2026-102267 se ejecutó el verificador real del backend con una clave EC
sintética y dos servidores HTTP efímeros en 127.0.0.1. El endpoint configurado
respondió 302 hacia otro endpoint con la clave sintética y el backend aceptó
su JWT ES256 con issuer/audience válidos. **FAIL** para el requisito de rechazar
sustitución de claves por redirección; ambos servidores fueron cerrados.
No se usaron Supabase, datos de usuarios ni credenciales reales.
Esto demuestra el riesgo cuando se controla la redirección; no prueba que un
atacante externo controle hoy nuestro JWKS. Evidencia:
`.docker/evidence/jwks-redirect-diagnosis.json`.

### S1: actualización Python mínima propuesta

- PyJWT 2.13.0 → **2.14.0**, manteniendo `[crypto]`.
- urllib3 2.7.0 → **2.8.0**, manteniendo Sentry y demás dependencias actuales.
- Elevar el mínimo directo de PyJWT a 2.14.0 y añadir en `[tool.uv]` la restricción
  `constraint-dependencies = ["urllib3>=2.8.0"]`, sin convertir Sentry en dependencia
  directa ni añadir extras nuevos. [Restricciones oficiales de uv](https://docs.astral.sh/uv/reference/settings/#constraint-dependencies).
- Resolver sobre el lock existente únicamente esos dos paquetes:
  `uv lock --upgrade-package pyjwt==2.14.0 --upgrade-package urllib3==2.8.0`.
  Revisar por nombre el diff completo del lock. Si cambia otra versión o se requiere
  otro paquete, detener la actualización y justificarlo antes de ampliar el alcance.
  Mantener `uv sync --locked` en las imágenes; no regenerar desde cero ni usar `--upgrade`.

Compatibilidad estática: PyJWT exige Python >=3.9 y urllib3 >=3.10, dentro del
>=3.11 del proyecto y Python 3.13.16 de Docker. Los wheels son universales;
PyJWT conserva `cryptography>=3.4.0`, compatible con el 50.0.0 ya fijado.
urllib3 no añade requisitos obligatorios en el conjunto de extras usado.
Las firmas y excepciones utilizadas por auth siguen disponibles.
[Metadata PyJWT](https://pypi.org/pypi/PyJWT/2.14.0/json),
[metadata urllib3](https://pypi.org/pypi/urllib3/2.8.0/json).

Riesgos funcionales: PyJWT 2.14.0 bloquea redirecciones y añade un cooldown de
30 segundos para refrescos de JWKS por kid desconocido. Una clave recién rotada
puede producir rechazo temporal durante ese intervalo. Se propone conservar la
protección y verificar rotación/caché/concurrencia, sin poner el cooldown a cero.
El endpoint interno debe entregar JWKS directamente. No hay evidencia que obligue
a cambiar `SUPABASE_JWKS_URL`, issuer o los checks JWT de Agrifos.
[Implementación 2.14.0](https://github.com/jpadilla/pyjwt/blob/2.14.0/jwt/jwks_client.py).

urllib3 corrige la separación TLS entre proxy/destino y puede afectar configuraciones
que dependían de la mezcla anterior; también limita líneas de tamaño de chunk.
Verificar importación/compatibilidad de Sentry y transporte, además del backend.
[Notas urllib3 2.8.0](https://github.com/urllib3/urllib3/releases/tag/2.8.0).
Las versiones candidatas **no están instaladas**: suite con ellas y nuevo escaneo
son **NOT RUN**, sujetos a aprobación.

### Debian: quince CVE y paquetes afectados

Todos estos hallazgos carecen de FixedVersion para Bookworm en el informe Trivy.
“Sin corrección” significa sin versión corregida acreditada para esa suite en las
fuentes consultadas; no significa que no exista parche upstream.
Los estados y versiones Trixie se contrastaron individualmente con Debian el 2026-10-08.
Las versiones de otra suite no deben instalarse mezcladas sobre Bookworm.

Mapa de paquetes/versión instalada, usado por las filas siguientes:

| Grupo | Paquetes binarios y versión |
|---|---|
| U | bsdutils `1:2.38.1-5+deb12u3`; libblkid1, libmount1, libsmartcols1, libuuid1, mount, util-linux y util-linux-extra `2.38.1-5+deb12u3` |
| N | libncursesw6, libtinfo6, ncurses-base y ncurses-bin `6.4-4` |
| Q | libsqlite3-0 `3.40.1-2+deb12u2` |
| D | libsystemd0 y libudev1 `252.39-1~deb12u2` |
| O | libssl3 y openssl `3.0.22-1~deb12u1` |

| CVE / severidad | Paquete(s) | Corrección / situación Debian | Aplicabilidad al runtime inspeccionado |
|---|---|---|---|
| [CVE-2023-45853](https://security-tracker.debian.org/tracker/CVE-2023-45853) CRITICAL | zlib1g `1:1.2.13.dfsg-1` | Bookworm: ignored/will_not_fix; Trixie zlib `1:1.3.dfsg+really1.3.1-1` figura fixed | MiniZip no se compila en este zlib de Bookworm; libminizip1 tampoco está instalado. Candidato a adjudicación documentada, no exclusión aplicada. |
| [CVE-2025-69720](https://security-tracker.debian.org/tracker/CVE-2025-69720) HIGH | N | Bookworm/Trixie abiertos; versión fixed en unstable `6.6+20251231-1` | Overflow de infocmp al analizar datos terminal. No se invoca desde app; no confundir bibliotecas presentes con la ruta concreta del CLI. |
| [CVE-2025-7458](https://security-tracker.debian.org/tracker/CVE-2025-7458) CRITICAL | Q | Bookworm no-dsa; Trixie `3.46.1-7+deb13u2` fixed | Requiere SQL SQLite arbitrario. Python sí puede importar sqlite3 3.40.1; app usa PostgreSQL y no se encontró SQL SQLite, pero la capacidad sigue disponible. |
| [CVE-2026-11822](https://security-tracker.debian.org/tracker/CVE-2026-11822) HIGH | Q | Bookworm postponed; Trixie `3.46.1-7+deb13u2` fixed | Datos FTS5 maliciosos y consultas MATCH. No se encontró carga de bases SQLite/FTS5 desde app. |
| [CVE-2026-11824](https://security-tracker.debian.org/tracker/CVE-2026-11824) HIGH | Q | Bookworm postponed; Trixie `3.46.1-7+deb13u2` fixed | Overflow FTS5 sobre base manipulada; mismo alcance condicionado anterior. |
| [CVE-2026-16742](https://security-tracker.debian.org/tracker/CVE-2026-16742) HIGH | D | Bookworm postponed/Trixie no-dsa; unstable fixed `261.2-1` | Requiere systemd-homed y cuenta local gestionada por él. Su ejecutable no está en esta imagen; no se ejecuta systemd como servicio. |
| [CVE-2026-41992](https://security-tracker.debian.org/tracker/CVE-2026-41992) HIGH | gzip `1.12-1` | Bookworm postponed; Trixie `1.13-1+deb13u1` fixed | Secuencia de archivos LZW/LZH manipulados en gzip -d. No hay ese procesamiento en endpoints inspeccionados. |
| [CVE-2026-53613](https://security-tracker.debian.org/tracker/CVE-2026-53613) HIGH | U | Bookworm abierto; Trixie `2.41.5-0+deb13u1` fixed | Carrera local en mount privilegiado. mount existe con SUID; UID 10001 reduce acceso, no basta para descartar cualquier escalada. |
| [CVE-2026-54369](https://security-tracker.debian.org/tracker/CVE-2026-54369) HIGH | libacl1 `2.3.1-3` | Bookworm postponed/Trixie no-dsa; unstable fixed `2.4.0-1`, nueva ABI | Requiere llamadas ACL por pathname desde proceso privilegiado y componentes manipulables. No se encontró tal uso en app. |
| [CVE-2026-76642](https://security-tracker.debian.org/tracker/CVE-2026-76642) HIGH | U | Bookworm/Trixie abiertos; unstable fixed `2.42.3-1` | Helper mount fallido seguido de hooks privilegiados. No hay mounts/fstab de usuario gestionados por app; herramientas siguen presentes. |
| [CVE-2026-78408](https://security-tracker.debian.org/tracker/CVE-2026-78408) HIGH | U | Bookworm/Trixie abiertos; unstable fixed `2.42.4-1` | nsenter --join-cgroup privilegiado contra destino controlado. nsenter existe, pero app no ejecuta esa operación. |
| [CVE-2026-78409](https://security-tracker.debian.org/tracker/CVE-2026-78409) HIGH | U | Bookworm/Trixie abiertos; unstable fixed `2.42.3-1` | X-mount.subdir, entrada fstab autorizada y fast path kernel >=6.15. No se identificó ese flujo en app. |
| [CVE-2026-78410](https://security-tracker.debian.org/tracker/CVE-2026-78410) HIGH | U | Bookworm/Trixie abiertos; unstable fixed `2.42.3-1` | Bind mount SUID con origen/ancestros reemplazables y hooks de permisos. No se identificó fstab ni flujo equivalente en app. |
| [CVE-2026-84782](https://security-tracker.debian.org/tracker/CVE-2026-84782) HIGH | O | Bookworm abierto; Trixie security `3.5.7-1~deb13u3` fixed | Handshake/retransmisión DTLS. OpenSSL 3.0.22 está cargado; app usa HTTP/TLS sobre TCP, sin DTLS observado. |
| [CVE-2026-9538](https://security-tracker.debian.org/tracker/CVE-2026-9538) HIGH | perl-base `5.36.0-7+deb12u4` | Bookworm/Trixie postponed; unstable fixed `5.42.3-1` | Agotamiento de memoria en Archive::Tar. No se encontró ese uso; la carga de ese módulo falló en la imagen inspeccionada. |

Las inferencias “no se encontró uso” se basan en código app y componentes de la imagen,
no en pruebas de explotación exhaustivas. El análisis completo de paquetes es
`.docker/evidence/scanners/summary.json`; las observaciones de componentes están en
`.docker/evidence/runtime-applicability.txt`. Ningún hallazgo se suprime.

### S2: alternativas para reducir Debian

| Alternativa | Ventaja | Límite / riesgo | Propuesta |
|---|---|---|---|
| Refrescar digest de Python 3.13.16-slim-bookworm | Conserva suite y ABI | Los 15 CVE de la tabla no tienen corrección Bookworm acreditada; un digest nuevo no garantiza resolverlos | Comparar inventario/scan si aparece una reconstrucción; no prometer cierre |
| APT selectivo fijado sobre Bookworm | Cambios limitados cuando existe backport de seguridad | No se acreditó uno para estos hallazgos; snapshot/versiones deben fijarse. apt upgrade genérico pierde control del alcance | No recomendar upgrade masivo ni paquetes de sid/trixie mezclados |
| Python 3.13.16-slim-trixie fijado por digest | Conserva Python y ecosistema glibc; Debian acredita correcciones para SQLite, gzip, zlib, un CVE util-linux y OpenSSL | Cambia suite, glibc/OpenSSL y bibliotecas; ncurses, ACL, systemd, Perl y otros CVE util-linux siguen abiertos | **Candidato preferido para evaluación aislada, previa aprobación** |
| Base mínima propia / retirar paquetes esenciales | Reduce utilidades que la API no necesita | mount/util-linux/perl forman parte de la base Debian; eliminarlos a mano puede romper dpkg, módulos Python o diagnóstico. Mantener imagen propia aumenta coste | No borrar bibliotecas ni metadata para engañar al scanner |
| Alpine o distroless | Menos paquetes en algunas imágenes | musl/wheels/build nativo o cambio del runtime/debug; amplio cambio sin ventaja medida | Fuera de la actualización mínima propuesta |

Existe el tag oficial Python 3.13.16-slim-trixie. Consulta de registro sin construir
ni cambiar Dockerfile: índice
`sha256:bf44cdfcb76cd3b41e879bc058fc37ec5872002ccfde7fcb765e218cde0cd79c`,
manifest linux/amd64
`sha256:8fb4cfa1a2616d7b8e0c2175cc6ad68f5729c34ea8488c0b360d2934b7be9024`.
El [Dockerfile oficial](https://github.com/docker-library/python/blob/d2a898cb88e46203577eabc62cdcf6e92aaee176/3.13/slim-trixie/Dockerfile)
conserva Python 3.13.16. **Build y escaneo del candidato: NOT RUN.**
La tabla Debian no sustituye comprobar los paquetes realmente presentes en ese digest.

Se propone evaluar ese candidato en una imagen de investigación separada, conservar
el lock y escanear la imagen completa tras S1. No adoptar Trixie hasta comprobar
imports, suite backend, Alembic/psycopg2/asyncpg, TLS, usuario y driver real.
No hay todavía una opción acreditada con cero HIGH/CRITICAL.

Como defensa adicional, proponer cap_drop ALL y no-new-privileges para API/migraciones,
comprobando su funcionamiento. La configuración actual garantiza UID 10001;
los controles añadidos a los contenedores de diagnóstico no demuestran que Compose
ya los tenga. Estos controles reducen capacidad de escalada; no corrigen los CVE.

Una adjudicación VEX/excepción por componente ausente podría ser defendible para
MiniZip o systemd-homed después de verificar cada binario/digest. Requiere
justificación específica y autorización; no se añade ahora. No utilizar
--ignore-unfixed, exclusiones globales ni exit-code 0 para convertir FAIL en PASS.
Eliminar fastapi-cloud-cli mediante el extra disponible
standard-no-fastapi-cloud-cli también reduciría Sentry/urllib3, pero altera más
paquetes y la experiencia CLI; no forma parte de S1.

## 3. Evidencia y validación pendiente

| Comprobación | Estado | Alcance / evidencia |
|---|---|---|
| Daemon actual Engine 29.1.3 | PASS | docker version devuelve Server |
| Publicación implícita restringida por bridge | FAIL | network-blockers-diagnosis.json; wildcard IPv4/IPv6 |
| Publicación nativa explícita 127.0.0.1 | PASS | Mismo informe; prueba de bindings sin servidor |
| Suite backend con dependencias actuales | PASS | 116 tests, 0 fallos; blockers-baseline-backend.txt; avisos de deprecación existentes |
| Rechazo de JWKS redirect con PyJWT actual | FAIL | jwks-redirect-diagnosis.json; diagnóstico HTTP/ES256 sintético |
| Metadata y APIs de versiones candidatas | PASS | Inspección estática de wheels con SHA256 contrastado; no prueba de ejecución |
| Suite/transportes con PyJWT 2.14.0 y urllib3 2.8.0 | NOT RUN | Requiere aprobación S1 |
| Adaptador propuesto con CLI real en Windows/Linux | NOT RUN | Requiere aprobación N1 |
| Escaneo de imagen corregida / candidato Trixie | NOT RUN | No se construyeron ni aplicaron esos candidatos |
| Integración real FastAPI/PostgreSQL/Alembic/Auth/ES256/MFA/persistencia | NOT RUN | El bloqueo de publicación sigue vigente |
| Licencias Android, SDK/NDK y APK | NOT RUN | Aceptación personal pendiente |

Los JSON/reportes originales y nuevos permanecen ignorados en .docker/evidence.
`blockers-evidence-manifest.json` registra SHA256 de los resultados de esta fase,
incluido el scan original. Fuentes consultadas/código/wheels de investigación están
en .docker/research, sin instalación ni inclusión en imágenes.
SHA256 del scan analizado:
`e61cc7a89c3de9a1d1f5ffc6c11f23d456b68afa2d745dc2a497c6324100ed35`.

Después de aprobar y validar N1, ejecutar el driver
`bash scripts/test-docker-integration.sh` (Git Bash explícito en Windows).
Debe conservar resultados individuales reales de salud FastAPI/DB, cabeza Alembic,
usuario/password Auth, firma ES256/issuer/audience/expiración, credenciales inválidas,
JWT alterado, enrolamiento y challenge TOTP, rechazo AAL1 y aceptación AAL2,
reinicio/persistencia y limpieza de los datos sintéticos propios.
Agregar pruebas HTTP de redirect/cache/rotación y repetir suite+scan tras S1.
Si falta Docker o falla una fase, registrar FAIL/NOT RUN; nunca rellenar éxito con mocks.
Linux host requiere ejecución propia o CI real; una sonda en Docker Desktop no la acredita.

## 4. Decisiones de aprobación y Git

Se solicita aprobación diferenciada para:

1. **N1:** mecanismo de lanzamiento local con adaptador, mismos servicios/red,
   controles de binding antes de start y preflight obligatorio. No cambios globales.
2. **S1:** exclusivamente PyJWT 2.14.0 y urllib3 2.8.0, mínimos/restricción y lock
   dirigido, regresiones y nueva imagen/scan.
3. **S2:** evaluación aislada de Python 3.13.16-slim-trixie y controles de privilegios.
   Su adopción final y cualquier excepción de seguridad requieren decisión basada
   en el resultado real, no quedan implícitas en aprobar S1.

Si se prefiere la política oficial Desktop a N1, su configuración global requiere
autorización explícita separada y comprobar que el preflight sigue siendo válido;
no se ha aplicado ni se garantiza que desbloquee 4.55.0.

Único archivo versionado añadido en esta fase: docs/docker-blockers-proposal.md.
Los Dockerfiles, scripts de arranque, manifiestos, lockfiles, configuración Auth y
documentos de validación anterior permanecen intactos.
Commit documental previsto: docs(docker): propose network and security blocker fixes.
No push, merge ni PR. main, origin/main y chore/backend-audit conservan
`a1df7e06943aef78c042340b65edb7e7e4113701`.
El trabajo de implementación de los bloqueantes espera aprobación.
