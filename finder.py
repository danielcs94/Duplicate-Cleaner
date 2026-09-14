import os
import hashlib
from pathlib import Path
from collections import defaultdict

# Carpetas que nunca queremos escanear: ruido técnico o zonas del sistema.
CARPETAS_EXCLUIDAS = {
    "node_modules", ".git", "venv", ".venv", "__pycache__",
    "Library", "Applications", ".Trash", "System", "vendor",
    ".npm", ".cache", "dist", "build",
}

# Paquetes/bundles que técnicamente son carpetas pero se gestionan solos
# (Fotos, apps...) — mejor no meternos dentro.
SUFIJOS_EXCLUIDOS = (".app", ".photoslibrary", ".fcpbundle", ".imovielibrary", ".bundle")

EXTENSIONES_IMAGEN = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".heic", ".tiff"}

# Carpeta real de iCloud Drive en macOS.
ICLOUD_DRIVE = Path.home() / "Library" / "Mobile Documents" / "com~apple~CloudDocs"


def es_imagen(ruta: Path) -> bool:
    return ruta.suffix.lower() in EXTENSIONES_IMAGEN


def es_cloud_only(ruta: Path) -> bool:
    """
    Heurística para detectar un archivo 'en la nube' (no descargado localmente) en macOS:
    un placeholder de iCloud declara su tamaño real pero apenas ocupa bloques en disco.
    Leer/hashear un archivo así obligaría a macOS a descargarlo primero, así que los
    detectamos ANTES de tocar su contenido para poder saltarlos.
    """
    try:
        st = ruta.stat()
    except (PermissionError, OSError):
        return False
    if st.st_size == 0:
        return False
    bloques_reales = st.st_blocks * 512
    return bloques_reales < st.st_size * 0.5


def raices_por_defecto():
    """Home del usuario + iCloud Drive (si existe) como raíces de escaneo por defecto."""
    raices = [Path.home()]
    if ICLOUD_DRIVE.exists():
        raices.append(ICLOUD_DRIVE)
    return raices


def escanear_archivos(raiz: Path):
    """Recorre `raiz` y devuelve todos los archivos, saltando carpetas excluidas, ocultas y bundles."""
    for dirpath, dirnames, filenames in os.walk(raiz):
        dirnames[:] = [
            d for d in dirnames
            if d not in CARPETAS_EXCLUIDAS
            and not d.startswith(".")
            and not d.endswith(SUFIJOS_EXCLUIDOS)
        ]
        for nombre in filenames:
            if nombre.startswith("."):
                continue
            yield Path(dirpath) / nombre


def escanear_archivos_multi(raices):
    """Igual que escanear_archivos pero sobre varias raíces, sin repetir archivos
    (por si alguna raíz queda anidada dentro de otra)."""
    vistos = set()
    for raiz in raices:
        if not raiz.exists():
            continue
        for ruta in escanear_archivos(raiz):
            try:
                real = ruta.resolve()
            except OSError:
                real = ruta
            if real in vistos:
                continue
            vistos.add(real)
            yield ruta


def hash_archivo(ruta: Path, bloque=65536) -> str:
    """Hash SHA-256 del contenido completo del archivo."""
    h = hashlib.sha256()
    try:
        with open(ruta, "rb") as f:
            while chunk := f.read(bloque):
                h.update(chunk)
    except (PermissionError, OSError):
        return ""
    return h.hexdigest()


def encontrar_duplicados_exactos(raices=None, progreso=None):
    """
    Agrupa archivos por tamaño primero (rápido), y solo calcula el hash completo
    dentro de cada grupo de mismo tamaño (evita hashear TODO el disco innecesariamente).

    Los archivos que están en la nube sin descargar se excluyen del hasheo (para no
    forzar su descarga) y se devuelven aparte, agrupados solo por nombre+tamaño
    (metadato que no requiere abrir el archivo).

    progreso: callback opcional progreso(fase: str, actual: int, total: int).

    Devuelve: (grupos_duplicados, grupos_en_la_nube)
    """
    raices = raices or raices_por_defecto()
    por_tamano = defaultdict(list)
    en_la_nube = []

    for ruta in escanear_archivos_multi(raices):
        try:
            tamano = ruta.stat().st_size
        except (PermissionError, OSError):
            continue
        if tamano == 0:
            continue
        if es_cloud_only(ruta):
            en_la_nube.append((ruta, tamano))
            continue
        por_tamano[tamano].append(ruta)

    candidatos = [rutas for rutas in por_tamano.values() if len(rutas) > 1]
    total_candidatos = sum(len(r) for r in candidatos)
    procesados = 0

    grupos = []
    for rutas in candidatos:
        por_hash = defaultdict(list)
        for ruta in rutas:
            h = hash_archivo(ruta)
            procesados += 1
            if progreso and procesados % 25 == 0:
                progreso("duplicados_exactos", procesados, total_candidatos)
            if h:
                por_hash[h].append(ruta)
        for iguales in por_hash.values():
            if len(iguales) > 1:
                grupos.append(iguales)

    posibles_nube = defaultdict(list)
    for ruta, tamano in en_la_nube:
        posibles_nube[(ruta.name, tamano)].append(ruta)
    grupos_nube = [g for g in posibles_nube.values() if len(g) > 1]

    return grupos, grupos_nube


def calcular_hash_perceptual(ruta: Path):
    """Hash perceptual de una imagen (para comparar por parecido visual, no bit a bit)."""
    try:
        from PIL import Image
        import imagehash
        with Image.open(ruta) as img:
            return imagehash.phash(img)
    except Exception:
        return None


def encontrar_imagenes_similares(raices=None, distancia_maxima=5, progreso=None):
    """
    Agrupa imágenes visualmente parecidas (aunque no sean el mismo archivo).
    Las imágenes que están en la nube sin descargar se saltan (abrir la imagen para
    calcular su huella forzaría la descarga).

    distancia_maxima: cuánto pueden diferir los hashes perceptuales para
    considerarse "la misma foto" — cuanto más bajo, más estricta la comparación.

    Devuelve: (grupos_similares, cantidad_saltadas_por_estar_en_la_nube)
    """
    raices = raices or raices_por_defecto()
    todas = [r for r in escanear_archivos_multi(raices) if es_imagen(r)]
    imagenes = [r for r in todas if not es_cloud_only(r)]
    saltadas_nube = len(todas) - len(imagenes)

    hashes = []
    total = len(imagenes)
    for i, ruta in enumerate(imagenes, 1):
        h = calcular_hash_perceptual(ruta)
        if h is not None:
            hashes.append((ruta, h))
        if progreso and (i % 25 == 0 or i == total):
            progreso("imagenes_similares", i, total)

    usadas = set()
    grupos = []

    for i in range(len(hashes)):
        if hashes[i][0] in usadas:
            continue
        ruta_i, hash_i = hashes[i]
        grupo = [ruta_i]
        for j in range(i + 1, len(hashes)):
            ruta_j, hash_j = hashes[j]
            if ruta_j in usadas:
                continue
            if hash_i - hash_j <= distancia_maxima:
                grupo.append(ruta_j)
                usadas.add(ruta_j)
        if len(grupo) > 1:
            usadas.add(ruta_i)
            grupos.append(grupo)

    return grupos, saltadas_nube


if __name__ == "__main__":
    import sys
    raices = [Path(sys.argv[1])] if len(sys.argv) > 1 else raices_por_defecto()
    print(f"Escaneando duplicados exactos en: {[str(r) for r in raices]}\n")

    grupos, grupos_nube = encontrar_duplicados_exactos(raices)
    print(f"Encontrados {len(grupos)} grupos de duplicados exactos.")
    print(f"({len(grupos_nube)} grupos más en archivos de iCloud sin descargar, sin confirmar)\n")

    for i, grupo in enumerate(grupos[:10], 1):
        print(f"Grupo {i} ({len(grupo)} copias):")
        for ruta in grupo:
            print(f"   - {ruta}")
        print()

    if len(grupos) > 10:
        print(f"... y {len(grupos) - 10} grupos más.")
