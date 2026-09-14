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

EXTENSIONES_IMAGEN = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".heic", ".tiff"}


def es_imagen(ruta: Path) -> bool:
    return ruta.suffix.lower() in EXTENSIONES_IMAGEN


def escanear_archivos(raiz: Path):
    """Recorre `raiz` y devuelve todos los archivos, saltando carpetas excluidas y ocultas."""
    for dirpath, dirnames, filenames in os.walk(raiz):
        # Modificar dirnames in-place para que os.walk no entre en esas carpetas
        dirnames[:] = [
            d for d in dirnames
            if d not in CARPETAS_EXCLUIDAS and not d.startswith(".")
        ]
        for nombre in filenames:
            if nombre.startswith("."):
                continue
            yield Path(dirpath) / nombre


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


def encontrar_duplicados_exactos(raiz: Path):
    """
    Agrupa archivos por tamaño primero (rápido), y solo calcula el hash completo
    dentro de cada grupo de mismo tamaño (evita hashear TODO el disco innecesariamente).
    Devuelve: lista de grupos, cada grupo es una lista de rutas idénticas.
    """
    por_tamano = defaultdict(list)
    for ruta in escanear_archivos(raiz):
        try:
            tamano = ruta.stat().st_size
        except (PermissionError, OSError):
            continue
        if tamano > 0:
            por_tamano[tamano].append(ruta)

    grupos = []
    for tamano, rutas in por_tamano.items():
        if len(rutas) < 2:
            continue
        por_hash = defaultdict(list)
        for ruta in rutas:
            h = hash_archivo(ruta)
            if h:
                por_hash[h].append(ruta)
        for h, iguales in por_hash.items():
            if len(iguales) > 1:
                grupos.append(iguales)

    return grupos


if __name__ == "__main__":
    import sys
    raiz = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.home()
    print(f"Escaneando duplicados exactos en: {raiz}\n")

    grupos = encontrar_duplicados_exactos(raiz)
    print(f"Encontrados {len(grupos)} grupos de duplicados exactos.\n")

    for i, grupo in enumerate(grupos[:10], 1):
        print(f"Grupo {i} ({len(grupo)} copias):")
        for ruta in grupo:
            print(f"   - {ruta}")
        print()

    if len(grupos) > 10:
        print(f"... y {len(grupos) - 10} grupos más.")


def calcular_hash_perceptual(ruta: Path):
    """Hash perceptual de una imagen (para comparar por parecido visual, no bit a bit)."""
    try:
        from PIL import Image
        import imagehash
        with Image.open(ruta) as img:
            return imagehash.phash(img)
    except Exception:
        return None


def encontrar_imagenes_similares(raiz: Path, distancia_maxima=5):
    """
    Agrupa imágenes visualmente parecidas (aunque no sean el mismo archivo).
    distancia_maxima: cuánto pueden diferir los hashes perceptuales para
    considerarse "la misma foto" — cuanto más bajo, más estricta la comparación.
    """
    imagenes = [r for r in escanear_archivos(raiz) if es_imagen(r)]

    hashes = []
    total = len(imagenes)
    print(f"  Calculando huellas de {total} imágenes...")
    for i, ruta in enumerate(imagenes, 1):
        h = calcular_hash_perceptual(ruta)
        if h is not None:
            hashes.append((ruta, h))
        if i % 25 == 0 or i == total:
            print(f"  {i}/{total} procesadas...", end="\r")
    print()

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

    return grupos
