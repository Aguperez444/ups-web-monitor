# UPS Monitor

**UPS Monitor** es un proyecto open-source para monitorear un UPS (Uninterruptible Power Supply) usando [Network UPS Tools (NUT)](https://networkupstools.org/), exponiendo los datos a través de una API en **FastAPI** y un frontend moderno en **NextJS**.

La idea es simple:

- NUT se encarga de hablar con el UPS (USB/HID/serial, drivers, etc.)
- El backend en Python + FastAPI lee los datos desde `upsc`
- El frontend en NextJS muestra toda la información con una interfaz prolija y agradable

---

## ✨ Características (plan / estado)

- ✅ Lectura de datos del UPS via `upsc` (NUT)
- ✅ API REST en FastAPI
  - `GET /ups/raw` → salida completa de `upsc` en JSON
  - `GET /ups/summary` → resumen amigable (voltajes, carga, estado, etc.)
- ⏳ Frontend en NextJS (dashboard web con gráficos y estado en tiempo real)
- ⏳ Logs históricos (guardar métricas para análisis)
- ⏳ Alertas (cuando se corta la luz, batería baja, etc.)

---

## 🧱 Arquitectura

```text
UPS (USB/HID/serial)
        │
        │  (drivers)
        ▼
      NUT (upsd + drivers)
        │
        │  `upsc ups@localhost`
        ▼
  FastAPI backend (Python)
        │
        │  JSON / HTTP
        ▼
  NextJS frontend (React)

```

  🔧 Requisitos

Linux con NUT instalado y configurado

Ejemplo: upsc ups@localhost debe funcionar en consola

Python 3.10+ (recomendado)

Node.js 18+ (para el frontend con NextJS, cuando lo agregues)

🚀 Backend (FastAPI)
1. Instalación

Desde la carpeta backend/:

cd backend
python3 -m venv venv
source venv/bin/activate   # en Linux
pip install -r requirements.txt


Si todavía no generaste requirements.txt, podés hacerlo con:

pip install fastapi uvicorn[standard]
pip freeze > requirements.txt

2. Configuración

Por defecto, el backend asume que tu UPS está configurado en NUT como:

[ups]
    driver = nutdrv_qx
    port = auto
    # ...


y que upsc ups@localhost devuelve datos válidos.

Si tu nombre en ups.conf es otro, editá UPS_NAME en backend/main.py.

3. Ejecutar el backend
cd backend
source venv/bin/activate
uvicorn main:app --reload --host 0.0.0.0 --port 8000


Endpoints disponibles:

Documentación automática:
http://localhost:8000/docs

Datos RAW:
GET http://localhost:8000/ups/raw

Resumen amigable:
GET http://localhost:8000/ups/summary

Ejemplo de respuesta de /ups/summary:

{
  "status": "OL TRIM",
  "load_percent": 24.0,
  "input_voltage": 245.6,
  "output_voltage": 210.0,
  "battery_charge": 100.0,
  "battery_voltage": 27.1,
  "output_frequency": 50.1,
  "raw": {
    "battery.charge": "100",
    "battery.voltage": "27.1",
    "input.voltage": "245.6",
    "ups.status": "OL TRIM",
    "...": "..."
  }
}

🌐 Frontend (NextJS)

⚠️ Todavía en construcción.

La idea es crear un dashboard en NextJS que consuma http://localhost:8000/ups/summary y muestre:

Estado del UPS (OL, OB, LB, TRIM, BOOST, etc.)

Voltaje de entrada/salida

Carga (%)

Nivel de batería

Gráficos en tiempo real / semi-tiempo real

Creación inicial sugerida:

cd ups-monitor
npx create-next-app@latest frontend


Luego, dentro de frontend, consumir la API del backend.

🧪 Roadmap / Ideas

 Historial de métricas (guardar en SQLite/Postgres)

 Gráficos de voltaje / carga vs tiempo

 Alertas configurables (Telegram/Discord/e-mail)

 Soporte para múltiples UPS

 Docker Compose (backend + frontend + NUT opcional)

🤝 Contribuciones

Contribuciones, issues y PRs son bienvenidos.
Si querés sumar soporte para otros modelos de UPS, nuevos gráficos o integraciones (Home Assistant, por ejemplo), adelante.

📜 Licencia

Este proyecto está bajo la licencia MIT.
Consultá el archivo LICENSE para más detalles.


---

## 3. Archivos del backend

### `backend/requirements.txt` (mínimo)

```text
fastapi
uvicorn[standard]
