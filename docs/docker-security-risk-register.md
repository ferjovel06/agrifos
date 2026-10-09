# Riesgos pendientes de la imagen Docker

Fecha: 2026-10-08, Guatemala. Gate actual: **FAIL_FINDINGS**, con **40 HIGH,
0 CRITICAL y ocho CVE** tras retirar `mount` (antes: 44 HIGH). No hay excepciones
ni VEX aprobados o aplicados. El escaneo real y su prueba de identidad completaron
correctamente; el fallo corresponde a hallazgos pendientes, sin errores operativos.
Véase la decisión concreta por grupo al final.

Referencia del escaneo histórico: Trivy 0.75.0, base de vulnerabilidades UpdatedAt
`2026-10-08T15:33:46.578791096Z`. Python 3.13.16 y el mismo `backend/uv.lock`.
La base adoptada es Debian Trixie por digest, tras las pruebas del
[informe de cierre](docker-closeout.md). Esta mejora no acredita ausencia de riesgo.

## Comparación histórica medida, antes de retirar mount

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

## Paquetes Trixie detectados en el escaneo histórico de 44 HIGH

| Grupo | Paquetes binarios y versión instalada | Entradas |
|---|---|---:|
| U | bsdutils `1:2.41.5-0+deb13u1`; libblkid1, liblastlog2-2, libmount1, libsmartcols1, libuuid1, mount y util-linux `2.41.5-0+deb13u1`; login `1:4.16.0-2+really2.41.5-0+deb13u1` | 9 por CVE, 36 en total |
| N | libncursesw6, libtinfo6, ncurses-base, ncurses-bin `6.5+20250216-2` | 4 |
| S | libsystemd0 y libudev1 `257.13-1~deb13u1` | 2 |
| A | libacl1 `2.3.2-2+b1` | 1 |
| P | perl-base `5.40.1-6+deb13u1` | 1 |

## Registro histórico por CVE, antes de retirar mount

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

### Revalidación histórica al resolver el conflicto del PR #76

El 2026-10-09T00:30Z (2026-10-08 Guatemala), una consulta APT actualizada en un
contenedor aislado de la misma base confirmó Candidate=Installed para los 17 binarios
afectados en Trixie/security/updates. El [índice oficial de backports amd64](https://deb.debian.org/debian/dists/trixie-backports/main/binary-amd64/Packages.xz)
no contenía ninguno de esos paquetes. Fue una lectura de metadatos para análisis,
sin instalaciones, mezcla de repositorios ni cambios APT del host.

El escaneo real del runtime con la resolución mantuvo 44 HIGH, cero CRITICAL y
config=0/image=1/identity=0. Se verificaron UID 10001, CapEff/CapBnd=0,
NoNewPrivs=1 y fstab sin entradas. mount y nsenter siguen presentes; systemd-homed
y Archive::Tar siguen ausentes. No se presume que estos controles eliminen los CVE.

Para CVE-2026-78409 existe una discrepancia de alcance: el [advisory upstream](https://github.com/util-linux/util-linux/security/advisories/GHSA-8f2p-47x3-43mv)
indica afectados >=2.42, mientras [Debian](https://security-tracker.debian.org/tracker/CVE-2026-78409)
marca Trixie 2.41.5 vulnerable. Requiere aclaración del mantenedor; no se excluyó.
Los parches upstream 2.41.6 no constituyen una actualización Debian Trixie soportada
disponible en los repositorios comprobados. Más evidencia en el [informe del conflicto](docker-pr76-merge.md).

Se detiene la remediación de estos ocho CVEs sin instalar paquetes de sid, retirar
componentes esenciales ni cambiar el gate. Recomendación: mantener el PR **Draft**
y el gate en **FAIL** hasta disponer de una base corregida o una decisión explícita
del propietario sobre riesgos concretos. No se recomienda fusionar con este estado.

Cualquier excepción futura debe especificar CVE, paquetes/versiones e imagen, motivo,
controles necesarios, responsable, vencimiento y condición de retirada. Requiere
aprobación humana previa y una nueva validación. Este documento no es una excepción
Trivy, no contiene allowlists y no cambia el resultado de CI.

## Revisión nueva y retiro mínimo de mount

Las consultas del 2026-10-09T02:43-02:50Z (2026-10-08 Guatemala) se ejecutaron
de nuevo, sin reutilizar los resultados de la revisión anterior. Los tags oficiales
`python:3.13-slim-trixie` y `python:3.13.16-slim-trixie` siguen resolviendo al digest
`sha256:bf44cdfcb76cd3b41e879bc058fc37ec5872002ccfde7fcb765e218cde0cd79c`.
El [manifiesto oficial](https://raw.githubusercontent.com/docker-library/official-images/master/library/python)
y el [Dockerfile oficial](https://raw.githubusercontent.com/docker-library/python/master/3.13/slim-trixie/Dockerfile)
siguen declarando Python 3.13.16: no existe un nuevo parche/digest 3.13 verificado
que corrija estos hallazgos.

APT actualizado en un contenedor aislado, con raíz read-only y listas/caché en tmpfs,
confirmó de nuevo Candidate=Installed para los 17 paquetes originales desde
Trixie/security/updates. El índice oficial backports amd64, Last-Modified
`2026-10-09T02:00:30Z`, no contenía ninguno. No se instalaron actualizaciones.
Se conservaron URL, fecha HTTP, bytes y SHA256 de las diez fuentes oficiales en
`.docker/evidence/pr76-close/security/fresh-official-source-proof.json`; los candidatos,
simulaciones y dependencias están en el mismo directorio ignorado.

La simulación individual identificó una eliminación compatible: `mount` no es
Essential ni Protected, y purgarlo elimina únicamente ese paquete. El commit
`a684633` aplica `apt-get purge --yes mount` solo al stage runtime. No usa autoremove,
no fuerza esenciales, no borra inventarios dpkg ni cambia development/test o locks.
Las búsquedas verificadas no encuentran llamadas a mount/umount/losetup/swapon/swapoff
en la aplicación, Alembic o el driver, ni llamadas shell literales en scripts/docker.
Los flags Docker `--mount` son operaciones del daemon del host.

La comprobación real del runtime confirmó **PASS**: paquete `mount` y sus cinco
ejecutables ausentes; imports FastAPI, SQLAlchemy, PyJWT, cryptography, psycopg2,
uvicorn, `_curses`, `_curses_panel`, `_uuid`, `_sqlite3`, `_ssl` y readline conservados.
También comprobó UID 10001, CapEff/CapBnd=0, NoNewPrivs=1, fstab vacío y ausencia
de systemd-homed y Archive::Tar. Evidencia:
`.docker/evidence/pr76-close/security/runtime-after-mount-proof.json`.

No se retiró `libncursesw6`: aunque APT permite purgarlo, el ELF de `_curses` y
`_curses_panel` enlaza con sus bibliotecas. `login` tiene Protected=yes.
Las simulaciones de otras bibliotecas fallan por PreDepends de componentes esenciales;
util-linux, bsdutils, perl-base, ncurses-base y ncurses-bin son Essential.
APT autoremove no propone ningún paquete. No hay otra eliminación mínima comprobada.

### Alcance actual y resultado medido

Imagen analizada: stage runtime de `a684633`, misma base y mismo `backend/uv.lock`.
Digest de configuración del runtime: `sha256:d13eb9cce92f5c64c78122b8a5c72fbf64149e218ea96dd451d7b15aa0408335`.
Las clasificaciones siguientes quedan limitadas a esa imagen verificada y a su
inventario. No se extienden automáticamente a imágenes futuras. CI construye y
escanea su propio runtime del HEAD publicado; su digest figura en el artifact del PR.

| Comprobación posterior al retiro | Estado actual |
|---|---|
| Retiro íntegro por APT e imports runtime | PASS |
| Trivy real y coincidencia del archivo escaneado | Escaneo completado; identidad PASS; gate FAIL_FINDINGS |
| Hallazgos medidos | 40 HIGH, 0 CRITICAL, ocho CVEs; 16 paquetes |
| Excepciones, VEX, política HIGH/CRITICAL | Ningún cambio ni aprobación |

El JSON real confirma 16 paquetes detectados por fuente y ausencia de las cuatro
filas de `mount`. Ningún CVE completo desaparece. Configuration=0, image=10,
identity=0, database=0, metadata=0; el gate devuelve 1. La actualización normal
de Trivy confirmó una DB vigente (NextUpdate 2026-10-09T15:33:46Z), sin flags de
congelación. Secretos y misconfiguraciones HIGH/CRITICAL reportados: cero.

| Grupo | Paquetes y versión restante | Entradas medidas |
|---|---|---:|
| U | bsdutils `1:2.41.5-0+deb13u1`; libblkid1, liblastlog2-2, libmount1, libsmartcols1, libuuid1 y util-linux `2.41.5-0+deb13u1`; login `1:4.16.0-2+really2.41.5-0+deb13u1`. `mount` ya no está instalado. | 8 por CVE, 32 |
| N | libncursesw6, libtinfo6, ncurses-base y ncurses-bin `6.5+20250216-2` | 4 |
| S | libsystemd0 y libudev1 `257.13-1~deb13u1` | 2 |
| A | libacl1 `2.3.2-2+b1` | 1 |
| P | perl-base `5.40.1-6+deb13u1` | 1 |

### Condiciones comunes de las cinco decisiones propuestas

Responsable **propuesto**, pendiente de aceptación: propietario/aprobador del PR #76.
Fecha propuesta de vencimiento/revisión: **2026-11-07**. No constituye una excepción
vigente ni delega a la automatización una aprobación de riesgo.

El alcance operativo es la API con perfil `api-runtime`: UID 10001, CapEff/CapBnd=0,
`cap_drop: [ALL]`, `no-new-privileges:true`, sin privileged, Docker socket ni binds
de archivos/directorios del host; puertos sensibles publicados solo a `127.0.0.1`
con el preflight activo, sin exposición LAN. Esta condición no describe todos los
contenedores: desarrollo, pruebas y el helper de migración tienen binds documentados
y no quedan cubiertos por una futura excepción limitada a la API runtime.

Revisar antes del vencimiento si aparece un paquete corregido Trixie/security/updates
o backport oficial compatible, un digest nuevo de la base o del runtime, cambia un
componente/topología/privilegio/binding, o se instala un componente hoy ausente.
Repetir imports, pruebas e integración y escaneo con identidad tras cualquier cambio.
Una aprobación futura debe indicar expresamente CVE, paquete/versiones, digest,
controles, responsable, vencimiento y retirada. **Se requiere aprobación humana
antes de crear una allowlist o VEX, incluso para los grupos S/P.** El gate permanece
estricto y los hallazgos permanecen visibles.

### U — util-linux: conservar el bloqueo tras el retiro mínimo

CVEs: [76642](https://security-tracker.debian.org/tracker/CVE-2026-76642),
[78408](https://security-tracker.debian.org/tracker/CVE-2026-78408),
[78409](https://security-tracker.debian.org/tracker/CVE-2026-78409) y
[78410](https://security-tracker.debian.org/tracker/CVE-2026-78410), sobre los ocho
paquetes U de la tabla. Correcciones Debian fuera de Trixie: `2.42.3-1` para
76642/78409/78410 y `2.42.4-1` para 78408; ningún candidato compatible disponible.

Clasificación propuesta: **affected, sin corrección compatible** para
76642/78408/78410; **indeterminado** para 78409 por el alcance discordante de las
fuentes. Se retiró el CLI mount, pero libmount y nsenter siguen presentes; no se
declara que las bibliotecas queden corregidas. NNP/capabilities/fstab reducen los
flujos privilegiados. Decisión propuesta al responsable común: conservar el bloqueo
y esperar paquetes oficiales, sin excluir estos CVEs; solicitar aclaración del
mantenedor para 78409 y revisar con las condiciones y fecha comunes.

### N — ncurses: conservar dependencias y esperar el paquete corregido

[CVE-2025-69720](https://security-tracker.debian.org/tracker/CVE-2025-69720), los cuatro
paquetes N `6.5+20250216-2`; corrección Debian unstable `6.6+20251231-1`.
Clasificación propuesta: **affected, sin corrección compatible**. infocmp está
presente, aunque la API no lo ejecuta ni acepta terminfo de clientes. Retirar datos,
CLI esencial o bibliotecas enlazadas por Python rompe el contrato de la base.
Decisión propuesta: mantener los cuatro hallazgos y el bloqueo, no procesar terminfo
no fiable y esperar el paquete oficial; revisión por el responsable y fecha comunes.

### S — systemd: evaluar no afectación por componente ausente

[CVE-2026-16742](https://security-tracker.debian.org/tracker/CVE-2026-16742),
libsystemd0/libudev1 `257.13-1~deb13u1`; corrección Debian unstable `261.2-1`.
Clasificación técnica propuesta: **not_affected / componente ausente**, limitada
al flujo de systemd-homed en esta imagen. La comprobación real no encuentra el
daemon ni un servicio systemd-homed; las bibliotecas permanecen por dependencias
de componentes esenciales. Esto no corrige su versión ni retira detecciones Trivy.
Decisión propuesta: someter esta no afectación al aprobador para el digest y las
condiciones comunes. Sin aprobación expresa, conservar ambas detecciones y el gate;
no se ha emitido ni aplicado VEX. Invalidar la propuesta si se instala/ejecuta homed.

### A — acl: conservar dependencia y esperar la actualización compatible

[CVE-2026-54369](https://security-tracker.debian.org/tracker/CVE-2026-54369),
libacl1 `2.3.2-2+b1`; corrección Debian unstable `2.4.0-1` con nuevo ABI.
Clasificación propuesta: **affected, sin corrección compatible**. La biblioteca es
PreDepends de coreutils/sed/tar; no se identifica una llamada ACL por pathname
privilegiada en la API. La restricción de privilegios reduce ese flujo, sin probar
inexplotabilidad. Debian señala que no se debe backportar mediante parches individuales.
Decisión propuesta: conservar el hallazgo y el bloqueo, sin retirada forzada o
mezcla sid; esperar el paquete oficial y revisar con el responsable y fecha comunes.

### P — perl: evaluar no afectación por módulo ausente

[CVE-2026-9538](https://security-tracker.debian.org/tracker/CVE-2026-9538), perl-base
`5.40.1-6+deb13u1`; corrección Debian unstable `5.42.3-1`, Archive::Tar >=3.10 upstream.
Clasificación técnica propuesta: **not_affected / componente ausente**, limitada
al parser Archive::Tar: su carga en el runtime falla con exit 2 y el módulo está
ausente. Perl-base es Essential; instalar un módulo nuevo innecesario no corregiría
el inventario fuente existente. Decisión propuesta: someter esta no afectación al
aprobador para el digest/condiciones comunes. Hasta esa aprobación, mantener el
hallazgo y el gate; no hay VEX aplicado. Invalidar si se instala Archive::Tar o se
introduce procesamiento de tar por Perl.
