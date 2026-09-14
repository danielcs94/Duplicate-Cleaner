from flask import Flask, render_template_string, jsonify, request, send_file, abort
import json
import threading
from io import BytesIO
import subprocess
from datetime import datetime
from pathlib import Path

from send2trash import send2trash

from finder import (
    encontrar_duplicados_exactos,
    encontrar_imagenes_similares,
    raices_por_defecto,
    es_imagen,
    es_cloud_only,
)

ICONOS_POR_EXTENSION = {
    ".pdf": "📄", ".doc": "📄", ".docx": "📄", ".txt": "📄", ".md": "📄",
    ".xls": "📊", ".xlsx": "📊", ".csv": "📊",
    ".ppt": "📽", ".pptx": "📽",
    ".zip": "📦", ".rar": "📦", ".7z": "📦", ".tar": "📦", ".gz": "📦",
    ".mp3": "🎵", ".wav": "🎵", ".m4a": "🎵",
    ".mp4": "🎬", ".mov": "🎬", ".avi": "🎬",
}

def icono_para(ruta_str):
    return ICONOS_POR_EXTENSION.get(Path(ruta_str).suffix.lower(), "📁")

app = Flask(__name__)

BASE_DIR = Path(__file__).parent
ESTADO_FILE = BASE_DIR / "estado.json"
RESULTADOS_FILE = BASE_DIR / "resultados.json"

_lock = threading.Lock()

# ── Estado / resultados en disco ───────────────────────────────

def load_estado():
    if ESTADO_FILE.exists():
        return json.loads(ESTADO_FILE.read_text())
    return {"escaneando": False, "ultimo_scan": None, "mensaje": None, "progreso": None}

def save_estado(data):
    ESTADO_FILE.write_text(json.dumps(data))

def load_resultados():
    if RESULTADOS_FILE.exists():
        return json.loads(RESULTADOS_FILE.read_text())
    return {"grupos_exactos": [], "grupos_similares": [], "grupos_nube": [], "saltadas_nube_imagenes": 0}

def save_resultados(data):
    RESULTADOS_FILE.write_text(json.dumps(data))

def formato_tamano(num_bytes):
    for unidad in ["B", "KB", "MB", "GB"]:
        if num_bytes < 1024:
            return f"{num_bytes:.0f} {unidad}" if unidad == "B" else f"{num_bytes:.1f} {unidad}"
        num_bytes /= 1024
    return f"{num_bytes:.1f} TB"

def info_archivo(ruta_str):
    ruta = Path(ruta_str)
    try:
        tamano = ruta.stat().st_size
    except (PermissionError, OSError):
        tamano = 0
    try:
        relativa = str(ruta.relative_to(Path.home()))
    except ValueError:
        relativa = str(ruta)
    imagen = es_imagen(ruta)
    nube = es_cloud_only(ruta) if ruta.exists() else False
    return {
        "ruta": str(ruta),
        "relativa": relativa,
        "tamano": tamano,
        "tamano_fmt": formato_tamano(tamano),
        "es_imagen": imagen,
        "cloud_only": nube,
        "icono": "☁️" if nube else icono_para(ruta_str),
    }

# ── Escaneo en segundo plano ────────────────────────────────────

def ejecutar_escaneo():
    estado = load_estado()
    estado["escaneando"] = True
    estado["mensaje"] = "Buscando duplicados exactos..."
    estado["progreso"] = None
    save_estado(estado)

    def progreso(fase, actual, total):
        e = load_estado()
        e["progreso"] = {"fase": fase, "actual": actual, "total": total}
        save_estado(e)

    try:
        raices = raices_por_defecto()
        grupos_exactos, grupos_nube = encontrar_duplicados_exactos(raices, progreso=progreso)

        estado = load_estado()
        estado["mensaje"] = "Buscando imágenes visualmente parecidas..."
        save_estado(estado)

        grupos_similares, saltadas_nube_imagenes = encontrar_imagenes_similares(raices, progreso=progreso)

        resultados = {
            "grupos_exactos": [[str(r) for r in g] for g in grupos_exactos],
            "grupos_similares": [[str(r) for r in g] for g in grupos_similares],
            "grupos_nube": [[str(r) for r in g] for g in grupos_nube],
            "saltadas_nube_imagenes": saltadas_nube_imagenes,
            "raices": [str(r) for r in raices],
        }
        save_resultados(resultados)

        estado = load_estado()
        estado["ultimo_scan"] = datetime.now().strftime("%d/%m/%Y %H:%M")
        estado["mensaje"] = (
            f"{len(grupos_exactos)} grupos de duplicados exactos, "
            f"{len(grupos_similares)} de imágenes parecidas, "
            f"{len(grupos_nube)} grupos en iCloud sin analizar."
        )
    except Exception as e:
        estado = load_estado()
        estado["mensaje"] = f"Error durante el escaneo: {e}"
    finally:
        estado["escaneando"] = False
        estado["progreso"] = None
        save_estado(estado)

# ── HTML ─────────────────────────────────────────────────────

HTML = '''<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Limpiador de Duplicados</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #f5f5f5; color: #1a1a1a; padding-bottom: 80px; }
header { background: white; border-bottom: 1px solid #e5e5e5; padding: 0 2rem; display: flex; align-items: center; gap: 1rem; height: 56px; flex-wrap: wrap; }
header h1 { font-size: 15px; font-weight: 600; margin-right: auto; }
.run-btn { background: white; border: 1px solid #ddd; border-radius: 8px; padding: 6px 14px; font-size: 12px; cursor: pointer; display:flex; align-items:center; gap:5px; }
.run-btn:hover { background: #f5f5f5; }
.run-btn:disabled { opacity: .6; cursor: default; }
.status-bar { background: #f0f9f5; border-bottom: 1px solid #d0eadf; padding: 6px 2rem; font-size: 12px; color: #0F6E56; }
.status-bar.scanning { background: #fff8e8; border-bottom-color: #f0dfae; color: #8a6d1f; }
.main { max-width: 1000px; margin: 0 auto; padding: 1.5rem; }
.metrics { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin-bottom: 1.5rem; }
.metric { background: white; border-radius: 12px; padding: 1.25rem; border: 1px solid #e5e5e5; }
.metric-label { font-size: 12px; color: #888; margin-bottom: 6px; }
.metric-value { font-size: 26px; font-weight: 600; }
.section-title { font-size: 13px; font-weight: 600; color: #444; text-transform: uppercase; letter-spacing: .05em; margin: 1.75rem 0 .75rem; }
.section-note { font-size: 12px; color: #999; margin-top: -0.5rem; margin-bottom: .75rem; }
.group { background: white; border-radius: 12px; border: 1px solid #e5e5e5; padding: 1rem 1.25rem; margin-bottom: 10px; }
.group-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
.group-head span { font-size: 12px; color: #888; }
.quick-btn { font-size: 11px; color: #0F6E56; background: none; border: none; cursor: pointer; text-decoration: underline; }
.file-row { display: flex; align-items: center; gap: 10px; padding: 6px 0; border-bottom: 1px solid #f5f5f5; font-size: 13px; }
.file-row:last-child { border-bottom: none; }
.file-row .ruta { flex: 1; word-break: break-all; color: #333; }
.file-row .tamano { color: #999; font-size: 11px; white-space: nowrap; }
.thumb { width: 42px; height: 42px; border-radius: 6px; object-fit: cover; flex-shrink: 0; background: #f0f0f0; border: 1px solid #eee; }
.thumb.icono { display: flex; align-items: center; justify-content: center; font-size: 18px; }
.ir-btn { font-size: 11px; color: #444; background: white; border: 1px solid #ddd; border-radius: 6px; padding: 4px 8px; cursor: pointer; white-space: nowrap; flex-shrink: 0; }
.ir-btn:hover { background: #f5f5f5; }
.lightbox { display: none; position: fixed; inset: 0; background: rgba(0,0,0,.75); align-items: center; justify-content: center; z-index: 100; cursor: zoom-out; }
.lightbox.open { display: flex; }
.lightbox img { max-width: 90vw; max-height: 90vh; border-radius: 8px; }
.empty { font-size: 13px; color: #bbb; padding: 1rem 0; }
.trash-bar { position: fixed; bottom: 0; left: 0; right: 0; background: white; border-top: 1px solid #e5e5e5; padding: 12px 2rem; display: none; align-items: center; justify-content: space-between; gap: 1rem; }
.trash-bar.visible { display: flex; }
.trash-bar .count { font-size: 13px; color: #444; }
.trash-btn { background: #D85A30; color: white; border: none; border-radius: 8px; padding: 8px 16px; font-size: 13px; cursor: pointer; }
.trash-btn:hover { background: #c04d26; }
.spinner { display:inline-block; width:12px; height:12px; border:2px solid #ddd; border-top-color:#1a1a1a; border-radius:50%; animation:spin .6s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
</style>
</head>
<body>

<header>
  <h1>🧹 Limpiador de Duplicados</h1>
  <button class="run-btn" id="runBtn" onclick="ejecutarEscaneo()">
    <span id="runIcon">▶</span> Escanear ahora
  </button>
</header>

<div class="status-bar {% if estado.escaneando %}scanning{% endif %}" id="statusBar">
  {% if estado.escaneando %}
    ⏳ {{ estado.mensaje or 'Escaneando...' }}
  {% elif estado.ultimo_scan %}
    ✓ Último escaneo: <strong>{{ estado.ultimo_scan }}</strong> — {{ estado.mensaje }}
  {% else %}
    Todavía no se ha escaneado nada. Pulsa "Escanear ahora" (puede tardar varios minutos la primera vez).
  {% endif %}
</div>

<div class="main">
  <div class="metrics">
    <div class="metric">
      <div class="metric-label">Espacio recuperable estimado</div>
      <div class="metric-value">{{ espacio_recuperable_fmt }}</div>
    </div>
    <div class="metric">
      <div class="metric-label">Grupos de duplicados</div>
      <div class="metric-value">{{ (resultados.grupos_exactos|length) + (resultados.grupos_similares|length) }}</div>
    </div>
    <div class="metric">
      <div class="metric-label">En iCloud sin analizar</div>
      <div class="metric-value">{{ resultados.grupos_nube|length }}</div>
    </div>
  </div>

  <div class="section-title">Duplicados exactos</div>
  {% if resultados.grupos_exactos %}
    {% for grupo in resultados.grupos_exactos %}
    <div class="group" data-grupo="exacto-{{ loop.index0 }}">
      <div class="group-head">
        <span>{{ grupo|length }} copias idénticas — {{ (info_map[grupo[0]].tamano_fmt) }} cada una</span>
        <button class="quick-btn" onclick="marcarTodasMenosLaPrimera('exacto-{{ loop.index0 }}')">Marcar todas menos la primera</button>
      </div>
      {% for ruta in grupo %}
      <label class="file-row">
        <input type="checkbox" class="chk" value="{{ ruta }}">
        {% if info_map[ruta].es_imagen and not info_map[ruta].cloud_only %}
        <img class="thumb" src="/miniatura?ruta={{ ruta | urlencode }}" loading="lazy" alt=""
             onclick="event.preventDefault(); abrirLightbox('/miniatura?ruta={{ ruta | urlencode }}&grande=1')">
        {% else %}
        <span class="thumb icono">{{ info_map[ruta].icono }}</span>
        {% endif %}
        <span class="ruta">{{ info_map[ruta].relativa }}</span>
        <span class="tamano">{{ info_map[ruta].tamano_fmt }}</span>
        <button type="button" class="ir-btn" onclick="event.preventDefault(); irAlArchivo('{{ ruta | replace("'", "\\'") }}')">Ir al archivo</button>
      </label>
      {% endfor %}
    </div>
    {% endfor %}
  {% else %}
    <div class="empty">Sin duplicados exactos (todavía).</div>
  {% endif %}

  <div class="section-title">Imágenes visualmente parecidas</div>
  {% if resultados.grupos_similares %}
    {% for grupo in resultados.grupos_similares %}
    <div class="group" data-grupo="similar-{{ loop.index0 }}">
      <div class="group-head">
        <span>{{ grupo|length }} imágenes parecidas (no idénticas bit a bit)</span>
        <button class="quick-btn" onclick="marcarTodasMenosLaPrimera('similar-{{ loop.index0 }}')">Marcar todas menos la primera</button>
      </div>
      {% for ruta in grupo %}
      <label class="file-row">
        <input type="checkbox" class="chk" value="{{ ruta }}">
        {% if info_map[ruta].es_imagen and not info_map[ruta].cloud_only %}
        <img class="thumb" src="/miniatura?ruta={{ ruta | urlencode }}" loading="lazy" alt=""
             onclick="event.preventDefault(); abrirLightbox('/miniatura?ruta={{ ruta | urlencode }}&grande=1')">
        {% else %}
        <span class="thumb icono">{{ info_map[ruta].icono }}</span>
        {% endif %}
        <span class="ruta">{{ info_map[ruta].relativa }}</span>
        <span class="tamano">{{ info_map[ruta].tamano_fmt }}</span>
        <button type="button" class="ir-btn" onclick="event.preventDefault(); irAlArchivo('{{ ruta | replace("'", "\\'") }}')">Ir al archivo</button>
      </label>
      {% endfor %}
    </div>
    {% endfor %}
  {% else %}
    <div class="empty">Sin imágenes parecidas encontradas (todavía).</div>
  {% endif %}

  <div class="section-title">En iCloud, sin descargar (sin analizar)</div>
  <div class="section-note">
    Coinciden en nombre y tamaño, pero no se han comparado byte a byte para no forzar su descarga.
    Revísalos tú antes de borrar nada — no hay checkbox aquí a propósito.
  </div>
  {% if resultados.grupos_nube %}
    {% for grupo in resultados.grupos_nube %}
    <div class="group">
      <div class="group-head"><span>{{ grupo|length }} archivos con el mismo nombre y tamaño</span></div>
      {% for ruta in grupo %}
      <div class="file-row">
        <span class="thumb icono">{{ info_map[ruta].icono }}</span>
        <span class="ruta">{{ info_map[ruta].relativa }}</span>
        <span class="tamano">{{ info_map[ruta].tamano_fmt }}</span>
        <button type="button" class="ir-btn" onclick="irAlArchivo('{{ ruta | replace("'", "\\'") }}')">Ir al archivo</button>
      </div>
      {% endfor %}
    </div>
    {% endfor %}
  {% else %}
    <div class="empty">Ninguno detectado.</div>
  {% endif %}
</div>

<div class="trash-bar" id="trashBar">
  <span class="count" id="trashCount">0 seleccionados</span>
  <button class="trash-btn" onclick="enviarAPapelera()">Enviar seleccionados a la papelera</button>
</div>

<div class="lightbox" id="lightbox" onclick="cerrarLightbox()">
  <img id="lightboxImg" src="" alt="">
</div>

<script>
const ULTIMO_SCAN_INICIAL = "{{ estado.ultimo_scan or '' }}";

async function irAlArchivo(ruta) {
  await fetch('/abrir', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ruta}),
  });
}

function abrirLightbox(src) {
  document.getElementById('lightboxImg').src = src;
  document.getElementById('lightbox').classList.add('open');
}

function cerrarLightbox() {
  document.getElementById('lightbox').classList.remove('open');
  document.getElementById('lightboxImg').src = '';
}

function marcarTodasMenosLaPrimera(grupoId) {
  const grupo = document.querySelector(`[data-grupo="${grupoId}"]`);
  const checks = grupo.querySelectorAll('.chk');
  checks.forEach((c, i) => { c.checked = i !== 0; });
  actualizarBarra();
}

function actualizarBarra() {
  const seleccionados = document.querySelectorAll('.chk:checked');
  const bar = document.getElementById('trashBar');
  const count = document.getElementById('trashCount');
  if (seleccionados.length > 0) {
    bar.classList.add('visible');
    count.textContent = seleccionados.length + ' seleccionados';
  } else {
    bar.classList.remove('visible');
  }
}

document.addEventListener('change', (e) => {
  if (e.target.classList.contains('chk')) actualizarBarra();
});

async function enviarAPapelera() {
  const rutas = Array.from(document.querySelectorAll('.chk:checked')).map(c => c.value);
  if (rutas.length === 0) return;
  if (!confirm(`¿Enviar ${rutas.length} archivo(s) a la papelera? Podrás recuperarlos desde ahí si te equivocas.`)) return;

  const res = await fetch('/eliminar', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({rutas}),
  });
  const data = await res.json();
  if (data.errores && data.errores.length > 0) {
    alert('Algunos archivos no se pudieron borrar:\\n' + data.errores.join('\\n'));
  }
  window.location.reload();
}

async function ejecutarEscaneo() {
  const btn = document.getElementById('runBtn');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> Escaneando...';

  await fetch('/escanear', {method: 'POST'});

  const intervalo = setInterval(async () => {
    const res = await fetch('/estado');
    const data = await res.json();
    if (!data.escaneando) {
      clearInterval(intervalo);
      window.location.reload();
    }
  }, 3000);
}

// Si ya había un escaneo en curso al cargar la página, seguimos vigilando.
if ({{ 'true' if estado.escaneando else 'false' }}) {
  ejecutarEscaneo();
}
</script>
</body>
</html>
'''

# ── Rutas ────────────────────────────────────────────────────

@app.route("/")
def index():
    estado = load_estado()
    resultados = load_resultados()

    todas_las_rutas = set()
    for clave in ("grupos_exactos", "grupos_similares", "grupos_nube"):
        for grupo in resultados.get(clave, []):
            todas_las_rutas.update(grupo)

    info_map = {ruta: info_archivo(ruta) for ruta in todas_las_rutas}

    espacio_recuperable = 0
    for grupo in resultados.get("grupos_exactos", []):
        if len(grupo) > 1:
            espacio_recuperable += info_map[grupo[0]]["tamano"] * (len(grupo) - 1)
    for grupo in resultados.get("grupos_similares", []):
        if len(grupo) > 1:
            espacio_recuperable += sum(info_map[r]["tamano"] for r in grupo[1:])

    return render_template_string(
        HTML,
        estado=estado,
        resultados=resultados,
        info_map=info_map,
        espacio_recuperable_fmt=formato_tamano(espacio_recuperable),
    )

@app.route("/escanear", methods=["POST"])
def escanear():
    estado = load_estado()
    if estado.get("escaneando"):
        return jsonify({"ok": True, "ya_en_curso": True})
    thread = threading.Thread(target=ejecutar_escaneo, daemon=True)
    thread.start()
    return jsonify({"ok": True})

@app.route("/estado")
def estado_actual():
    return jsonify(load_estado())

def _rutas_conocidas():
    resultados = load_resultados()
    rutas = set()
    for clave in ("grupos_exactos", "grupos_similares", "grupos_nube"):
        for grupo in resultados.get(clave, []):
            rutas.update(grupo)
    return rutas

@app.route("/miniatura")
def miniatura():
    ruta_str = request.args.get("ruta", "")
    if ruta_str not in _rutas_conocidas():
        abort(404)

    ruta = Path(ruta_str)
    if not ruta.exists() or not es_imagen(ruta) or es_cloud_only(ruta):
        abort(404)

    grande = request.args.get("grande") == "1"
    tamano_max = (800, 800) if grande else (160, 160)

    try:
        from PIL import Image
        img = Image.open(ruta)
        img.thumbnail(tamano_max)
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        buf = BytesIO()
        img.save(buf, format="JPEG", quality=85)
        buf.seek(0)
    except Exception:
        abort(404)

    respuesta = send_file(buf, mimetype="image/jpeg")
    respuesta.headers["Cache-Control"] = "public, max-age=86400"
    return respuesta

@app.route("/abrir", methods=["POST"])
def abrir_en_finder():
    datos = request.get_json(silent=True) or {}
    ruta_str = datos.get("ruta", "")

    if ruta_str not in _rutas_conocidas():
        return jsonify({"ok": False, "error": "ruta no reconocida"}), 404

    ruta = Path(ruta_str)
    if not ruta.exists():
        return jsonify({"ok": False, "error": "el archivo ya no existe"}), 404

    try:
        subprocess.run(["open", "-R", str(ruta)], check=True)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

    return jsonify({"ok": True})

@app.route("/eliminar", methods=["POST"])
def eliminar():
    datos = request.get_json(silent=True) or {}
    rutas_pedidas = set(datos.get("rutas") or [])

    resultados = load_resultados()
    rutas_validas = set()
    for clave in ("grupos_exactos", "grupos_similares"):
        for grupo in resultados.get(clave, []):
            rutas_validas.update(grupo)

    eliminados = []
    errores = []

    with _lock:
        for ruta_str in rutas_pedidas:
            if ruta_str not in rutas_validas:
                errores.append(f"{ruta_str}: no proviene del último escaneo, ignorado")
                continue
            try:
                send2trash(ruta_str)
                eliminados.append(ruta_str)
            except Exception as e:
                errores.append(f"{ruta_str}: {e}")

        if eliminados:
            eliminados_set = set(eliminados)
            for clave in ("grupos_exactos", "grupos_similares"):
                nuevos_grupos = []
                for grupo in resultados.get(clave, []):
                    restante = [r for r in grupo if r not in eliminados_set]
                    if len(restante) > 1:
                        nuevos_grupos.append(restante)
                resultados[clave] = nuevos_grupos
            save_resultados(resultados)

    return jsonify({"ok": True, "eliminados": eliminados, "errores": errores})

if __name__ == "__main__":
    print("Dashboard disponible en http://localhost:5051")
    app.run(port=5051, debug=False)
