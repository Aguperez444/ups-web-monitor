# 📦 UPS Monitor

**Monitoreo moderno y open-source para tu UPS usando NUT, FastAPI y
NextJS**

UPS Monitor es una herramienta open-source que permite obtener
información en tiempo real de un UPS (Uninterruptible Power Supply) a
través de **Network UPS Tools (NUT)**, exponiendo una API en **FastAPI**
y un dashboard web moderno en **NextJS**.

------------------------------------------------------------------------

## 🚀 Funcionalidades

### **Backend (FastAPI)**

-   ✅ Lectura del UPS mediante `upsc` (NUT)
-   ✅ API REST:
    -   `GET /ups/raw` → salida completa de `upsc`
    -   `GET /ups/summary` → datos procesados (estado, voltajes, carga,
        etc.)
-   ⏳ Logs históricos en base de datos
-   ⏳ Alertas (corte eléctrico, batería baja, variaciones de voltaje)

### **Frontend (NextJS)**

-   ⏳ Dashboard moderno con:
    -   Estado del UPS
    -   Gráficos en tiempo real
    -   Voltajes de entrada/salida
    -   Nivel de batería y carga

------------------------------------------------------------------------

## 🧩 Arquitectura General

``` text
UPS (USB / HID / Serial)
        │
        ▼
      NUT (upsd + drivers)
        │  → upsc ups@localhost
        ▼
    FastAPI (Python)
        │  → JSON / HTTP
        ▼
    NextJS (React)
```

------------------------------------------------------------------------

## 🔧 Requisitos

-   Linux con **NUT** correctamente configurado\
    (ejemplo: `upsc ups@localhost` debe funcionar)
-   Python **3.10+**
-   Node.js **18+** (para el frontend)
-   Acceso al dispositivo del UPS (USB/HID/serial)

------------------------------------------------------------------------

# 🐍 Backend --- FastAPI

## 1️⃣ Instalación

``` bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Si aún no generaste el archivo:

``` bash
pip install fastapi uvicorn[standard]
pip freeze > requirements.txt
```

------------------------------------------------------------------------

## 2️⃣ Configuración

``` ini
[ups]
    driver = nutdrv_qx
    port = auto
```

Si tu UPS se llama distinto, modificá `UPS_NAME` en `backend/main.py`.

------------------------------------------------------------------------

## 3️⃣ Ejecutar el backend

``` bash
cd backend
source venv/bin/activate
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### 📚 Documentación automática

http://localhost:8000/docs

------------------------------------------------------------------------

## 📡 Endpoints principales

### **RAW completo**

`GET /ups/raw`

### **Resumen amigable**

`GET /ups/summary`

#### Ejemplo:

``` json
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
    "ups.status": "OL TRIM"
  }
}
```

------------------------------------------------------------------------

# 🌐 Frontend --- NextJS

⚠️ En desarrollo.

### Creación inicial:

``` bash
cd ups-monitor
npx create-next-app@latest frontend
```

Luego consumir:

`http://localhost:8000/ups/summary`

------------------------------------------------------------------------

# 🧪 Roadmap

-   [ ] Historial y métricas (SQLite/Postgres)\
-   [ ] Gráficos de carga y voltaje\
-   [ ] Alertas via Telegram / Discord / Email\
-   [ ] Soporte multi-UPS\
-   [ ] Docker Compose (NUT + backend + frontend)

------------------------------------------------------------------------

# 🤝 Contribuir

Contribuciones abiertas.\
Se aceptan mejoras de API, UI, integraciones externas y soporte para más
modelos de UPS.

------------------------------------------------------------------------

# 📄 Licencia

Licencia **MIT** (ver archivo LICENSE).

------------------------------------------------------------------------

## 📁 Requisitos del backend

    fastapi
    uvicorn[standard]
