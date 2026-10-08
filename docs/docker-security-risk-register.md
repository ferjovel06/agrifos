# Riesgos pendientes de la imagen Docker

Fecha: 2026-10-08. Estado del gate: **FAIL**, sin excepciones aprobadas ni aplicadas.
Trivy 0.75.0, base de vulnerabilidades UpdatedAt
`2026-10-08T15:33:46.578791096Z`. Python 3.13.16 y el mismo `backend/uv.lock`.
La base adoptada es Debian Trixie por digest, tras las pruebas del
[informe de cierre](docker-closeout.md). Esta mejora no acredita ausencia de riesgo.

## Comparación medida

| Resultado HIGH/CRITICAL | Bookworm | Trixie |
|---|---:|---:|
| Entradas OS | 55 | 44 |
| HIGH | 53 | 44 |
| CRITICAL | 2 | 0 |
| CVEs distintos | 15 | 8 |
| Entradas Python | 0 | 0 |
| Secretos/configuración de runtime | 0 | 0 |
| Gate | FAIL | FAIL |

Las entradas repiten un mismo CVE por paquete binario de un paquete fuente.
Se conservan todas: no son 44 vulnerabilidades independientes, pero tampoco ocho
hallazgos automáticamente aceptados. Los JSON completos quedan en la evidencia local
ignorada; los campos siguientes son públicos y no contienen credenciales.

## Paquetes Trixie detectados

| Grupo | Paquetes binarios y versión instalada | Entradas |
|---|---|---:|
| U | bsdutils `1:2.41.5-0+deb13u1`; libblkid1, liblastlog2-2, libmount1, libsmartcols1, libuuid1, mount y util-linux `2.41.5-0+deb13u1`; login `1:4.16.0-2+really2.41.5-0+deb13u1` | 9 por CVE, 36 en total |
| N | libncursesw6, libtinfo6, ncurses-base, ncurses-bin `6.5+20250216-2` | 4 |
| S | libsystemd0 y libudev1 `257.13-1~deb13u1` | 2 |
| A | libacl1 `2.3.2-2+b1` | 1 |
| P | perl-base `5.40.1-6+deb13u1` | 1 |

## Registro por CVE

Todos tienen severidad **HIGH** en este escaneo y carecen de `FixedVersion` Trixie
en el informe. Las correcciones de sid/unstable citadas no constituyen un paquete
compatible autorizado para instalar en Trixie. No se mezclan repositorios Debian.

| CVE y fuente Debian | Grupo | Corrección publicada fuera de Trixie | Condiciones de explotación y aplicabilidad observada |
|---|---|---|---|
| [CVE-2026-76642](https://security-tracker.debian.org/tracker/CVE-2026-76642) | U | util-linux `2.42.3-1` en unstable | Hooks posteriores a mount-helper fallido con operaciones privilegiadas. mount está presente; la API no lo invoca y fstab no tiene montajes autorizados. |
| [CVE-2026-78408](https://security-tracker.debian.org/tracker/CVE-2026-78408) | U | util-linux `2.42.4-1` en unstable | nsenter --join-cgroup ejecutado con privilegios contra un destino controlado deja autoridad mediante un FD. nsenter está presente; no es una operación del backend. |
| [CVE-2026-78409](https://security-tracker.debian.org/tracker/CVE-2026-78409) | U | util-linux `2.42.3-1` en unstable | Fast path X-mount.subdir con Linux >=6.15, entrada fstab autorizada y symlinks controlables. fstab de la imagen no configura entradas de ese tipo. |
| [CVE-2026-78410](https://security-tracker.debian.org/tracker/CVE-2026-78410) | U | util-linux `2.42.3-1` en unstable | Carrera en origen de bind mount autorizado y cambios privilegiados de propietario/permisos. Requiere control local de rutas y la operación privilegiada. |
| [CVE-2025-69720](https://security-tracker.debian.org/tracker/CVE-2025-69720) | N | ncurses `6.6+20251231-1` en unstable | Overflow en infocmp al analizar entradas manipuladas. infocmp está presente; el servicio FastAPI no lo ejecuta ni procesa terminfo suministrado por clientes. |
| [CVE-2026-16742](https://security-tracker.debian.org/tracker/CVE-2026-16742) | S | systemd `261.2-1` en unstable | Escalada local en cuentas gestionadas por systemd-homed. Se detectan bibliotecas; systemd-homed no está instalado ni hay servicio systemd en este contenedor. |
| [CVE-2026-54369](https://security-tracker.debian.org/tracker/CVE-2026-54369) | A | acl `2.4.0-1` en unstable, con nuevas funciones ABI | Operaciones ACL por pathname de un llamador privilegiado frente a symlinks controlados. La biblioteca está presente; no se identificó ese flujo en Agrifos. |
| [CVE-2026-9538](https://security-tracker.debian.org/tracker/CVE-2026-9538) | P | perl `5.42.3-1` en unstable; Archive::Tar >=3.10 upstream | Agotamiento de memoria con archivos tar manipulados. El intérprete perl-base está instalado, pero cargar Archive::Tar falla porque ese módulo no está disponible en la imagen evaluada. |

Estos datos limitan la exposición observada; no demuestran inexplotabilidad general,
no sustituyen el escaneo ni autorizan una exclusión. Una ejecución con root,
privileged, montajes del host o herramientas administrativas puede cambiar el análisis.
Las fuentes Debian califican varios problemas como minor/no-dsa o postponed;
se conserva la severidad original de Trivy en CI.

## Medidas aplicadas y alternativas descartadas

Compose ejecuta API/desarrollo/runtime/migrate como UID 10001, con `cap_drop: [ALL]`
y `no-new-privileges:true`. La integración verifica UID, NoNewPrivs=1 y CapBnd=0
en el proceso real de la API. Esto impide adquirir privilegios mediante SUID y reduce
las condiciones de los avisos locales; no elimina el software vulnerable. Los comandos
Docker ejecutados fuera de Compose deben aplicar sus propios controles.

Trixie retira del escaneo los avisos de SQLite, gzip, OpenSSL, zlib/MiniZip y
CVE-2026-53613 presentes en Bookworm, manteniendo el mismo Python y dependencias.
No se actualizaron paquetes Python adicionales ni se retiraron librerías arbitrariamente.

Una simulación aislada de retirar util-linux, perl-base y libtinfo6 terminó con
código 100 por dependencias esenciales/conflicto con bash y ncurses-bin.
util-linux y perl-base están marcados Essential. No se aplicó esa eliminación:
forzarla o reconstruir la base desde paquetes mezclados introduciría un nuevo contrato
runtime, pérdida de soporte y pruebas adicionales fuera de esta corrección mínima.
La simulación no acredita que toda reducción futura sea imposible; una base reducida
requiere una evaluación independiente de las dependencias transitivas y mantenimiento.

## Decisión pendiente

Se detiene la remediación de estos ocho CVEs sin instalar paquetes de sid, retirar
componentes esenciales ni cambiar el gate. Recomendación: mantener el PR **Draft**
y el gate en **FAIL** hasta disponer de una base corregida o una decisión explícita
del propietario sobre riesgos concretos. No se recomienda fusionar con este estado.

Cualquier excepción futura debe especificar CVE, paquetes/versiones e imagen, motivo,
controles necesarios, responsable, vencimiento y condición de retirada. Requiere
aprobación humana previa y una nueva validación. Este documento no es una excepción
Trivy, no contiene allowlists y no cambia el resultado de CI.
