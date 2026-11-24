# UPS Monitor

Monitor web de un UPS mediante Network UPS Tools (NUT), FastAPI y Next.js. Muestra lecturas en vivo, el flujo de alimentación y hasta 30 días de historial persistente en SQLite por defecto.

- **Flujo eléctrico** muestra la entrada, la salida, la batería y el modo que reporta NUT.
- **Información UPS** reúne los indicadores de capacidad y carga con cuatro secciones de lectura que se pueden abrir juntas.
- **Historial** compara cinco métricas en gráficos independientes. Permite elegir las métricas y consultar intervalos de 15 minutos a 7 días, o fechas personalizadas dentro de la ventana de retención.

## Versión de producción (AppImage con bandeja del sistema)

Podés compilar un único archivo portable `dist/UPS-Monitor-x86_64.AppImage` autocontenido (Python + FastAPI + PyQt6 + dashboard estático en un solo proceso):

```sh
./packaging/build_appimage.sh
```

Al ejecutar `./dist/UPS-Monitor-x86_64.AppImage`:

- Se inicia el servidor web y el muestreador de NUT en segundo plano y aparece un ícono de batería/energía en la bandeja del sistema (KDE Plasma / Wayland / X11).
- **Click izquierdo** en el ícono abre el dashboard en el navegador predeterminado (`http://127.0.0.1:5601`).
- **Click derecho** muestra el estado en vivo, permite activar/desactivar **Iniciar con el sistema** (`~/.config/autostart/ups-monitor.desktop`), abrir la carpeta de datos o editar `~/.config/ups-monitor/config.env`.
- La base de datos SQLite se guarda de forma persistente en `~/.local/share/ups-monitor/ups.sqlite3` (con retención de 30 días por defecto y checkpoint WAL al cerrar) para conservar los registros al cerrar la app o reiniciar la PC.

## Inicio rápido (desarrollo)

Necesitás NUT instalado y configurado en el equipo que accede al UPS. Desde el equipo del backend, verificá que el cliente pueda leerlo.

```sh
upsc ups@localhost
```

Desde la raíz del proyecto, con Python 3.10 o posterior:

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
cd backend
python run.py
```

Desde otra terminal, con Node.js 20.9 o posterior:

```sh
cd frontend
npm ci
npm run dev
```

Abrí el dashboard en el puerto `3000`. La API escucha en el puerto `5601` y Swagger se sirve en `/docs`. Si usás un nombre de UPS distinto, definí `UPS_NAME` antes de iniciar el backend.

El navegador consulta Next.js en el mismo origen. Configurá `UPS_API_URL` en `frontend/.env.local` si Next.js debe conectarse a otro host o puerto.

## Arquitectura

```text
UPS → NUT (driver y upsd) → upsc → adaptador NutSource
                                          │
                                 puertos del dominio
                                          │
                                  casos de uso Monitor
                                     │            │
                              SQLiteSampleStore   FastAPI ← proxy Next.js ← dashboard
```

El dominio usa tipos de Python. Los casos de uso dependen de los puertos de lectura y persistencia. FastAPI inyecta el monitor, configura el muestreador en su ciclo de vida y traduce lecturas y muestras a esquemas HTTP.

- [Backend, API, persistencia y configuración](backend/README.md)
- [Frontend, proxy y verificación](frontend/README.md)

Licencia MIT. Ver [LICENSE](LICENSE).
