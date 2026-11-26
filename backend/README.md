# Backend de UPS Monitor

## Arquitectura

| Capa | Responsabilidad |
| --- | --- |
| `ups_monitor/domain` | Telemetría, muestras, modos y puertos de lectura y persistencia. |
| `ups_monitor/application` | Lectura actual, captura, consulta de historial, retención y ciclo periódico. |
| `ups_monitor/infrastructure` | Adaptadores para `upsc` y SQLite, y configuración por variables de entorno. |
| `ups_monitor/presentation` | Composición de dependencias, ciclo de vida de FastAPI, rutas y esquemas HTTP. |

`python run.py` desde `backend/` conserva el arranque anterior en el puerto `5601`. Desde la raíz también podés ejecutar `uvicorn backend.main:app --host 0.0.0.0 --port 5601`. Usá un proceso de Uvicorn por UPS y base para evitar muestreadores redundantes.

## Configuración

| Variable de entorno | Predeterminado | Descripción |
| --- | --- | --- |
| `UPS_NAME` | `ups@localhost` | Identificador que recibe `upsc`, por ejemplo `rack@servidor-nut`. |
| `UPS_DB_PATH` | `backend/data/ups.sqlite3` | Archivo SQLite. Una ruta relativa se interpreta desde el directorio de ejecución. |
| `UPS_UPSC_TIMEOUT_SECONDS` | `3` | Límite por invocación de `upsc`. |
| `UPS_SAMPLE_INTERVAL_SECONDS` | `10` | Segundos de espera entre ciclos de muestreo. |
| `UPS_RETENTION_HOURS` | `720` (30 días) | Horas de historial consultable. |
| `UPS_CLEANUP_INTERVAL_SECONDS` | `60` | Cadencia de limpieza, comprobada en cada ciclo. |
| `UPS_FRONTEND_DIST` | *(vacío)* | Directorio del export estático del frontend para servirlo desde FastAPI en `/`. |
| `UPS_STALE_RECOVERY_ENABLED` | `true` | Reinicia los servicios locales de NUT automáticamente si `upsc` devuelve `Data stale`. |
| `UPS_STALE_RECOVERY_COMMAND` | *(automático)* | Comando personalizado de recuperación. Por defecto usa `sudo -n systemctl restart nut-driver@<ups>.service nut-server.service` (con respaldo `systemctl --no-ask-password`) para objetivos locales. |
| `UPS_STALE_RECOVERY_COOLDOWN_SECONDS` | `60` | Segundos mínimos entre intentos automáticos de reinicio. |
| `UPS_STALE_RECOVERY_TIMEOUT_SECONDS` | `15` | Tiempo máximo de espera del comando de reinicio. |
| `UPS_STALE_RECOVERY_RETRY_DELAY_SECONDS` | `1.5` | Pausa tras reiniciar NUT antes de reintentar `upsc`. |

El cliente `upsc` debe estar en el `PATH` del backend. Para diagnosticar el equipo, ejecutá `upsc "$UPS_NAME"` con el mismo identificador que usa la API. La lectura actual consulta NUT directamente. El muestreador captura desde el arranque en un hilo de trabajo, registra los errores y vuelve a intentar en el siguiente ciclo. La limpieza también se ejecuta si NUT falla.

### Recuperación automática ante `Data stale`

Cuando `upsc` falla con `Data stale` en un UPS local (por ejemplo `ups@localhost`), el backend ejecuta automáticamente `sudo -n systemctl restart nut-driver@<ups>.service nut-server.service` (con un período de enfriamiento de 60 s y bloqueo para evitar reinicios simultáneos) y reintenta la lectura tras una breve pausa.

Para que el reinicio funcione sin pedir contraseña interactivamente, agregá una regla restringida en `sudoers` (con `sudo visudo -f /etc/sudoers.d/ups-monitor-nut`):

```text
<tu-usuario> ALL=(root) NOPASSWD: /usr/bin/systemctl restart nut-driver@ups.service nut-server.service
```

Podés comprobar que no pide clave con:

```sh
sudo -n systemctl restart nut-driver@ups.service nut-server.service
```

También podés habilitarlo con una regla de `polkit` (el backend prueba `systemctl --no-ask-password` si `sudo -n` requiere contraseña) o definir `UPS_STALE_RECOVERY_COMMAND` / desactivarlo con `UPS_STALE_RECOVERY_ENABLED=false`.

## API

Swagger está disponible en `/docs`.

| Operación | Contrato |
| --- | --- |
| `GET /api/ups/current` | Estado en vivo, timestamp UTC, modo, identificador, datos de equipo y cargador cuando NUT los informa. Devuelve HTTP 503 si falla la lectura o la telemetría es inutilizable. |
| `GET /api/metrics` | Rango solicitado, intervalo nominal de muestreo, tamaño de bucket si hubo reducción y muestras en orden cronológico. Consulta SQLite aunque NUT esté caído. |
| `GET /ups/raw` | Mapa de variables que devuelve `upsc`. |
| `GET /ups/summary` | Resumen anterior con sus campos de telemetría y el mapa `raw`. |
| `GET /saludo` | Respuesta de compatibilidad `{"chao":"mundo"}`. |

El historial acepta `start` y `end` en ISO 8601 con zona horaria. Ambos extremos son inclusivos. También acepta `window_minutes` en lugar de `start` para consultar un intervalo relativo a `end`. Si se omite `end`, se usa la hora actual. El rango predeterminado es de una hora. `max_points` acepta de 3 a 5000 y vale 600 por defecto.

```text
GET /api/metrics?window_minutes=15
GET /api/metrics?window_minutes=600&max_points=300
GET /api/metrics?start=2026-11-23T12:00:00Z&end=2026-11-23T14:00:00Z
```

Un rango válido que no contiene datos devuelve `samples: []`. La retención se aplica a la consulta incluso entre limpiezas. La reducción conserva la primera y la última muestra y selecciona una muestra real de cada bucket temporal interior. Un pico breve puede quedar entre las muestras seleccionadas. Para revisarlo, pedí un intervalo más corto o aumentá `max_points`.

## SQLite y disponibilidad de métricas

`ups_samples` es una tabla ancha con clave primaria `(ups_name, timestamp_us)` e índice sobre `timestamp_us` para retención. Cada captura guarda el estado de NUT y las columnas nullable `input_voltage`, `output_voltage`, `output_frequency`, `load_percent`, `battery_voltage` y `battery_charge`. El timestamp usa microsegundos UTC desde la época de Unix y la API lo expone en ISO 8601. SQLite usa WAL. El modo se obtiene del estado almacenado al consultar.

La disponibilidad depende del UPS y del driver. Por ejemplo, NUT puede no publicar `output.frequency`, o puede publicar `battery.charge` sin `battery.voltage`. Los valores ausentes o inválidos quedan en `null`. El cero se conserva cuando es un valor real. Se descartan capturas sin telemetría utilizable y el estado transitorio `WAIT`. El flujo en vivo se basa en los indicadores de [estado de NUT](https://networkupstools.org/docs/developer-guide.chunked/new-drivers.html) y del [cargador](https://networkupstools.org/docs/developer-guide.chunked/_variables.html). El esquema de conversión es conceptual, ya que el driver puede no identificar la topología interna.

## Pruebas

Desde la raíz y con el entorno Python activado:

```sh
pip install -r backend/requirements-dev.txt
python -m unittest discover -s backend/tests -v
```

Las pruebas ejercitan las rutas y su ciclo de vida, el parser de NUT, el muestreador y SQLite con una base temporal. No requieren conectar un UPS.
