import subprocess
from typing import Dict, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware


UPS_NAME = "ups@localhost"  # Ajustar si tu NUT usa otro nombre


def read_ups_raw() -> Dict[str, str]:
    """
    Llama a `upsc ups@localhost` y lo parsea a dict {clave: valor}.
    """
    try:
        output = subprocess.check_output(
            ["upsc", UPS_NAME],
            text=True,
            stderr=subprocess.STDOUT,
        )
    except subprocess.CalledProcessError as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error ejecutando upsc: {e.output.strip()}",
        )

    data: Dict[str, str] = {}
    for line in output.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        data[key.strip()] = value.strip()
    return data


def _safe_float(value: Optional[str]) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def build_summary(raw: Dict[str, str]) -> Dict:
    """
    Arma un resumen “amigable” a partir del dict crudo de upsc.
    """
    return {
        "status": raw.get("ups.status"),
        "load_percent": _safe_float(raw.get("ups.load")),
        "input_voltage": _safe_float(raw.get("input.voltage")),
        "output_voltage": _safe_float(raw.get("output.voltage")),
        "battery_charge": _safe_float(raw.get("battery.charge")),
        "battery_voltage": _safe_float(raw.get("battery.voltage")),
        "output_frequency": _safe_float(raw.get("output.frequency")),
        "raw": raw,
    }


app = FastAPI(
    title="UPS Monitor API",
    description="API para exponer datos de un UPS a través de NUT (upsc).",
    version="1.0.0",
)

# CORS para permitir frontend en localhost:3000 (NextJS)
origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)


@app.get("/ups/raw")
def get_ups_raw():
    """
    Devuelve TODO lo que tira `upsc` tal cual, pero como JSON.
    """
    return read_ups_raw()


@app.get("/ups/summary")
def get_ups_summary():
    """
    Devuelve un resumen con las cosas más útiles ya parseadas.
    Ideal para el frontend.
    """
    raw = read_ups_raw()
    return build_summary(raw)

@app.get("/saludo")
def get_ups_summary():
    return {"chao": "mundo"}