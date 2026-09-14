# 🧹 Limpiador de Duplicados

Herramienta local (Python + Flask) que escanea tu Mac —tu carpeta de usuario e iCloud
Drive— en busca de archivos duplicados: exactos (documentos, archivos de cualquier
tipo) e imágenes visualmente parecidas aunque no sean el mismo archivo.

## Cómo funciona

- **`finder.py`** — motor de escaneo. Agrupa archivos por tamaño y hashea (SHA-256)
  solo dentro de cada grupo de mismo tamaño, para no hashear todo el disco. Para
  imágenes, además calcula un hash perceptual (`imagehash`) y agrupa las que se
  parecen visualmente aunque no sean bit a bit idénticas.
- **Archivos de iCloud sin descargar** ("en la nube") se detectan por heurística
  (ocupan muy pocos bloques reales en disco pese a declarar su tamaño completo) y se
  excluyen del hasheo para no forzar su descarga — se listan aparte, agrupados solo
  por nombre y tamaño, para que decidas tú si merece la pena bajarlos y comparar.
- **`dashboard.py`** — dashboard web local. Lanza el escaneo en segundo plano,
  muestra los grupos de duplicados con checkboxes, y solo borra lo que marques
  explícitamente — siempre a la papelera (`send2trash`), nunca borrado permanente.

## Cómo ejecutar

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

python dashboard.py
# → http://localhost:5051
```

## Carpetas excluidas del escaneo

Carpetas técnicas (`node_modules`, `vendor`, `venv`, `.git`, cachés...), zonas de
sistema (`Library`, `Applications`, `.Trash`) y bundles que se gestionan solos
(`.app`, `.photoslibrary`, etc.) — salvo iCloud Drive, que se escanea explícitamente
aunque viva dentro de `Library`.

## Tecnologías

- Python
- Flask
- Pillow + ImageHash (comparación visual de imágenes)
- Send2Trash (borrado seguro, recuperable)
