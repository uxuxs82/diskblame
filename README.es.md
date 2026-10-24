# diskblame

![ci](https://github.com/uxuxs82/diskblame/actions/workflows/ci.yml/badge.svg)

[english](README.md) | [русский](README.ru.md) | [español](README.es.md) | [中文](README.zh-CN.md)

`diskblame` guarda un historial ligero del uso del disco y te dice qué cambió.

`du` y `ncdu` muestran el estado actual. `diskblame` guarda instantáneas de metadatos en SQLite, así que puedes preguntar qué creció desde la semana pasada, qué directorio tiene la culpa y por qué un archivo sigue ahí.

Nunca copia tus archivos.

## ¿por qué no usar solo du?

`du` y `ncdu` responden "qué es grande ahora". No responden "qué creció desde la semana pasada" a menos que guardes copias completas o recuerdes los números. `diskblame` guarda unos pocos números por ruta y los compara después.

Está pensado para cuando el almacenamiento ya está justo: un teléfono, un VPS pequeño o un portátil con el disco lleno. La base solo tiene metadatos, así que una instantánea de un directorio de 100 GiB suele ocupar unos pocos megabytes.

| herramienta | guarda historial | explica una ruta |
| --- | --- | --- |
| `du`, `ncdu` | no | no |
| `duc` | estado actual indexado | no |
| `snapdiff` | compara dos árboles | no |
| `diskblame` | instantáneas de metadatos | `diff` y `why` |

## instalación

Requiere Python 3.11 o superior. No tiene dependencias de ejecución.

```sh
pipx install git+https://github.com/uxuxs82/diskblame.git
```

O desde una copia local:

```sh
git clone https://github.com/uxuxs82/diskblame.git
cd diskblame
pip install .
```

En Termux:

```sh
pkg install python
pip install .
```

## inicio rápido

```sh
diskblame snap ~
diskblame snap ~
diskblame diff --since 7d
```

La primera instantánea es la base. La segunda le da a `diff` algo con lo que comparar.

Muestra los directorios más grandes:

```sh
diskblame top --depth 2
```

Muestra los archivos más grandes:

```sh
diskblame top --files --limit 30
```

Explica un archivo:

```sh
diskblame why ~/storage/shared/DCIM/Camera/IMG_0001.jpg
```

`why` muestra el tamaño, tipo, edad, estado de git, duplicados, referencias en archivos de texto cercanos y si la ruta parece caché o directorio de compilación. No afirma que un archivo sea seguro de borrar. Da los hechos y un veredicto conservador.

## comandos

| comando | qué hace |
| --- | --- |
| `snap [path]` | escanea un directorio y guarda una instantánea |
| `diff` | compara dos instantáneas, por defecto las dos últimas |
| `top` | muestra los directorios o archivos más grandes de una instantánea |
| `why <path>` | explica un archivo o directorio |
| `chart` | muestra el tamaño total a lo largo del tiempo |
| `watch` | avisa cuando un directorio crece por encima de un límite |
| `prune` | borra instantáneas antiguas |
| `config` | muestra o crea el archivo de configuración |

Opciones útiles:

```sh
diskblame snap ~ --exclude '*.log' --min-file-size 5MiB
diskblame diff --since 30d --path DCIM --limit 10
diskblame diff --files --limit 50
diskblame why ~/Downloads/archive.zip --no-refs
diskblame chart --days 90
diskblame prune --keep 20 --vacuum
diskblame watch --root ~ --since 7d --max-growth 1GiB --snap --interval 1h
```

La mayoría de los comandos aceptan `--json` para scripts.

## cómo funciona

Una instantánea guarda:

- una fila por directorio con tamaño total, número de archivos y número de directorios
- una fila por archivo igual o mayor que `min_file_size`, por defecto 1 MiB
- metadatos de la instantánea: raíz, hora, tamaño total, número de archivos, número de directorios y tiempo de escaneo

Los totales de directorio incluyen todos los archivos, incluso los que están por debajo del umbral. El umbral solo limita qué archivos individuales se guardan para `top --files`, `diff --files` y la comprobación de duplicados. `diff --files` muestra cambios de tamaño, no de contenido.

Los enlaces duros se cuentan una vez en los totales de directorio. Los enlaces simbólicos se omiten salvo que se use `--follow-symlinks`. Las entradas ilegibles se cuentan y se muestran, no se tratan como cero.

La base de datos está en `~/.local/share/diskblame/diskblame.db` por defecto. Una instantánea de unos cientos de miles de rutas es pequeña comparada con una copia completa de los archivos.

## configuración

La configuración por defecto es `~/.config/diskblame/config.toml`. Créala con:

```sh
diskblame config --init
```

Ejemplo:

```toml
[scan]
exclude = [".git", ".hg", ".svn", "__pycache__", ".DS_Store", "lost+found"]
min_file_size = "1MiB"
follow_symlinks = false

[db]
path = "~/.local/share/diskblame/diskblame.db"
```

`--db` y `--config` cambian las rutas para un solo comando.

## limitaciones

- Guarda metadatos, no el contenido de los archivos. No puede restaurar nada.
- No es una herramienta de copia de seguridad ni sustituye a `du`, `ncdu` o `duc`.
- Los tamaños de directorio dependen de la contabilidad de bloques del sistema de archivos. Los archivos dispersos pueden mostrar un tamaño menor que su longitud aparente.
- La detección de duplicados compara archivos guardados del mismo tamaño y luego los hashea. Para archivos grandes usa el primer y el último MiB más el tamaño.
- La búsqueda de referencias usa `git grep` dentro de un repositorio y un escaneo limitado de archivos de texto fuera de él.
- `watch` es un bucle en primer plano. Ejecútalo en tmux o en un gestor de servicios si quieres que siga vivo.

## contribuir

las issues y los pull requests son bienvenidos. mira [CONTRIBUTING.md](CONTRIBUTING.md).

## licencia

MIT
