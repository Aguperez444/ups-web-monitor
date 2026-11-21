#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd -P "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
BUILD_DIR="$ROOT_DIR/build"
APPDIR="$BUILD_DIR/AppDir"
DIST_DIR="$ROOT_DIR/dist"
TOOLS_DIR="$BUILD_DIR/tools"
PYTHON_CACHE_DIR="$BUILD_DIR/python-standalone"
FRONTEND_STAGE_DIR="$BUILD_DIR/frontend-export"

PYTHON_VERSION="${UPS_BUILD_PYTHON_VERSION:-3.12}"
ARCH="${ARCH:-$(uname -m)}"
OUTPUT_APPIMAGE="$DIST_DIR/UPS-Monitor-${ARCH}.AppImage"
APPIMAGETOOL="$TOOLS_DIR/appimagetool-${ARCH}.AppImage"

log() {
  printf '\n\033[1;36m==>\033[0m %s\n' "$1"
}

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Error: se requiere '$1' en el PATH." >&2
    exit 1
  fi
}

require_cmd uv
require_cmd node
require_cmd npm
require_cmd curl

mkdir -p "$BUILD_DIR" "$DIST_DIR" "$TOOLS_DIR" "$PYTHON_CACHE_DIR"

# 1. Build static export of the Next.js dashboard without altering frontend/ source
log "Compilando frontend Next.js en modo estático (output: export)…"
rm -rf "$FRONTEND_STAGE_DIR"
mkdir -p "$FRONTEND_STAGE_DIR"

if [ ! -d "$ROOT_DIR/frontend/node_modules" ]; then
  log "Instalando dependencias de frontend…"
  (cd "$ROOT_DIR/frontend" && npm ci)
fi

cp -a \
  "$ROOT_DIR/frontend/app" \
  "$ROOT_DIR/frontend/public" \
  "$ROOT_DIR/frontend/package.json" \
  "$ROOT_DIR/frontend/package-lock.json" \
  "$ROOT_DIR/frontend/next.config.ts" \
  "$ROOT_DIR/frontend/tsconfig.json" \
  "$ROOT_DIR/frontend/postcss.config.mjs" \
  "$FRONTEND_STAGE_DIR/"
# Dev-only proxy route handlers are served natively by FastAPI in production.
rm -rf "$FRONTEND_STAGE_DIR/app/api"
ln -s "$ROOT_DIR/frontend/node_modules" "$FRONTEND_STAGE_DIR/node_modules"

(
  cd "$FRONTEND_STAGE_DIR"
  NEXT_STATIC_EXPORT=1 NEXT_TELEMETRY_DISABLED=1 npx next build --webpack
)

if [ ! -f "$FRONTEND_STAGE_DIR/out/index.html" ]; then
  echo "Error: no se generó $FRONTEND_STAGE_DIR/out/index.html" >&2
  exit 1
fi

# 2. Provision relocatable standalone CPython via uv
log "Preparando Python ${PYTHON_VERSION} autocontenido…"
uv python install "$PYTHON_VERSION" --install-dir "$PYTHON_CACHE_DIR" --no-bin
PYTHON_SRC_DIR="$(find "$PYTHON_CACHE_DIR" -maxdepth 1 -mindepth 1 -type d -name "cpython-${PYTHON_VERSION}.*" | sort | tail -n 1)"
if [ -z "$PYTHON_SRC_DIR" ] || [ ! -x "$PYTHON_SRC_DIR/bin/python3" ]; then
  echo "Error: no se encontró el intérprete standalone de Python ${PYTHON_VERSION} en $PYTHON_CACHE_DIR" >&2
  exit 1
fi

# 3. Assemble AppDir
log "Ensamblando AppDir en $APPDIR…"
rm -rf "$APPDIR"
mkdir -p \
  "$APPDIR/usr/python" \
  "$APPDIR/usr/share/ups-monitor/backend" \
  "$APPDIR/usr/share/ups-monitor/desktop" \
  "$APPDIR/usr/share/ups-monitor/frontend" \
  "$APPDIR/usr/share/icons/hicolor/scalable/apps"

cp -a "$PYTHON_SRC_DIR/." "$APPDIR/usr/python/"
PY_STDLIB="$(find "$APPDIR/usr/python/lib" -maxdepth 1 -type d -name 'python3.*' | head -n 1)"

# Install backend + PyQt6 runtime dependencies inside the bundled Python
log "Instalando dependencias Python (FastAPI, Uvicorn, PyQt6) dentro del AppDir…"
uv pip install \
  --python "$APPDIR/usr/python/bin/python3" \
  --target "$PY_STDLIB/site-packages" \
  --no-compile \
  -r "$ROOT_DIR/packaging/requirements-desktop.txt"

# Copy application sources and static frontend
cp -a "$ROOT_DIR/backend/__init__.py" "$ROOT_DIR/backend/main.py" "$ROOT_DIR/backend/ups_monitor" \
  "$APPDIR/usr/share/ups-monitor/backend/"
cp -a "$ROOT_DIR/desktop/." "$APPDIR/usr/share/ups-monitor/desktop/"
cp -a "$FRONTEND_STAGE_DIR/out/." "$APPDIR/usr/share/ups-monitor/frontend/"

# Trim build-only/test files to keep AppImage compact
log "Limpiando archivos innecesarios (tests, cachés, cabeceras)…"
rm -rf \
  "$PY_STDLIB/test" \
  "$PY_STDLIB/idlelib" \
  "$PY_STDLIB/tkinter" \
  "$PY_STDLIB/turtledemo" \
  "$PY_STDLIB/ensurepip" \
  "$APPDIR/usr/python/include" \
  "$APPDIR/usr/python/share" \
  "$PY_STDLIB/site-packages/PyQt6/bindings"

# Remove large unused Qt6 translations (keep English and Spanish)
QT_TRANS="$PY_STDLIB/site-packages/PyQt6/Qt6/translations"
if [ -d "$QT_TRANS" ]; then
  find "$QT_TRANS" -type f ! -name '*_es.qm' ! -name '*_en.qm' -delete
fi

find "$APPDIR" -type d -name "__pycache__" -prune -exec rm -rf {} +
find "$APPDIR" -type f \( -name "*.pyc" -o -name "*.pyo" -o -name "*.pyi" -o -name "*.a" \) -delete

# Desktop metadata and icons (PNG for .DirIcon/AppImage thumbnail + SVG for scalable hicolor theme)
cp -a "$ROOT_DIR/packaging/ups-monitor.desktop" "$APPDIR/ups-monitor.desktop"
cp -a "$ROOT_DIR/desktop/assets/ups-monitor.svg" "$APPDIR/usr/share/icons/hicolor/scalable/apps/ups-monitor.svg"

if command -v rsvg-convert >/dev/null 2>&1; then
  rsvg-convert -w 256 -h 256 "$ROOT_DIR/desktop/assets/ups-monitor.svg" -o "$APPDIR/ups-monitor.png"
else
  QT_QPA_PLATFORM=offscreen \
  PYTHONHOME="$APPDIR/usr/python" \
  PYTHONPATH="$APPDIR/usr/share/ups-monitor" \
  "$APPDIR/usr/python/bin/python3" - "$APPDIR/ups-monitor.png" <<'PYEOF'
import sys
from PyQt6.QtGui import QGuiApplication
from desktop.icons import _render_pixmap

app = QGuiApplication([])
pixmap = _render_pixmap(256, "line", 80.0)
assert pixmap.save(sys.argv[1], "PNG"), "No se pudo guardar ups-monitor.png"
PYEOF
fi
cp -a "$APPDIR/ups-monitor.png" "$APPDIR/.DirIcon"

if command -v desktop-file-validate >/dev/null 2>&1; then
  desktop-file-validate "$APPDIR/ups-monitor.desktop"
fi

# Create AppRun entrypoint
cat > "$APPDIR/AppRun" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

HERE="$(dirname "$(readlink -f "$0")")"

# Preserve original host environment so external tools (xdg-open, browser, upsc) run cleanly
export UPS_ORIG_LD_LIBRARY_PATH="${LD_LIBRARY_PATH:-}"
export UPS_ORIG_QT_PLUGIN_PATH="${QT_PLUGIN_PATH:-}"
export UPS_ORIG_QT_QPA_PLATFORM_PLUGIN_PATH="${QT_QPA_PLATFORM_PLUGIN_PATH:-}"
export UPS_ORIG_PYTHONHOME="${PYTHONHOME:-}"
export UPS_ORIG_PYTHONPATH="${PYTHONPATH:-}"

export UPS_RUNNING_IN_APPIMAGE="1"
export UPS_FRONTEND_DIST="${UPS_FRONTEND_DIST:-$HERE/usr/share/ups-monitor/frontend}"
export PYTHONDONTWRITEBYTECODE="1"
export PYTHONNOUSERSITE="1"
export PYTHONHOME="$HERE/usr/python"
export PYTHONPATH="$HERE/usr/share/ups-monitor"
export QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-wayland;xcb}"

exec "$HERE/usr/python/bin/python3" -m desktop.tray_app "$@"
EOF
chmod +x "$APPDIR/AppRun"

# Ensure all files inside AppDir are world-readable/traversable for AppImage portability
chmod -R a+rX "$APPDIR"

# 4. Obtain appimagetool if needed and package the AppImage
if [ ! -x "$APPIMAGETOOL" ]; then
  log "Descargando appimagetool (${ARCH})…"
  curl -fL "https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-${ARCH}.AppImage" \
    -o "$APPIMAGETOOL"
  chmod +x "$APPIMAGETOOL"
fi

log "Generando $OUTPUT_APPIMAGE…"
rm -f "$OUTPUT_APPIMAGE"
if ! ARCH="$ARCH" "$APPIMAGETOOL" --no-appstream "$APPDIR" "$OUTPUT_APPIMAGE"; then
  ARCH="$ARCH" "$APPIMAGETOOL" --appimage-extract-and-run --no-appstream "$APPDIR" "$OUTPUT_APPIMAGE"
fi
chmod +x "$OUTPUT_APPIMAGE"

log "AppImage generado correctamente:"
ls -lh "$OUTPUT_APPIMAGE"
