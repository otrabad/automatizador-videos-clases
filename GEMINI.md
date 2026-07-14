# Instrucciones y Memoria de Desarrollo: Cobertura de Marca de Agua Interactiva

Este documento sirve como registro técnico y guía para futuras actualizaciones de la aplicación de automatización de video-clases.

## Descripción de la Funcionalidad

Se ha implementado una característica que permite cubrir marcas de agua anteriores (como logotipos corporativos o texto de plantillas de diapositivas) mediante una caja negra opaca y sólida que superpone un texto personalizado o firma del docente.

### Archivos Modificados/Creados
1. **`automatizador.py` (Core):** Aloja el motor de procesamiento de imágenes y ensamblado de MoviePy, además de la lógica de renderizado unbuffered (`flush=True`).
2. **`app.py` (UI Streamlit):** Aloja los controles deslizantes e interactivos de la interfaz web, el panel de diagnóstico visual de la tipografía y la visualización moderna de imágenes.
3. **`Arial.ttf` (Fuente Tipográfica):** Archivo de fuente Arial empaquetado directamente en la raíz del proyecto para asegurar un renderizado idéntico independientemente de si la plataforma de ejecución es macOS (local), Windows o Linux (nube de Streamlit Community Cloud / Docker).
4. **`config.json` (Ajustes predeterminados):** Almacena los valores iniciales para ejecuciones por línea de comandos (CLI).

---

## Cómo Funciona la Lógica Interna

### 1. Extracción y Estampado Local (Cero Costo de Procesamiento)
Para evitar la lentitud que supone re-renderizar o codificar videos con FFmpeg al final, la aplicación realiza el estampado **directamente sobre los archivos PNG de las diapositivas extraídas** bajo la carpeta temporal `temp_assets/`.

La función principal encargada de esto es:
```python
def aplicar_firma_a_slide(imagen_path, texto_firma="Dr. Omar Trabadelo", posicion="derecha", font_size=36, padding=30):
```
*   **Pillow (PIL):** Abre cada slide PNG extraído, calcula dinámicamente las dimensiones del texto de la firma utilizando la tipografía Arial provista en la raíz del proyecto (`Arial.ttf`).
*   **Caja Opaca Sólida:** Genera un rectángulo RGBA negro `(0, 0, 0, 255)` con un tamaño igual al tamaño del texto más el `padding` configurado.
*   **Ubicación (Frente de la Pantalla):**
    *   **Derecha:** Esquina inferior derecha `x = W - box_w - 20`, `y = H - box_h - 20`.
    *   **Izquierda:** Esquina inferior izquierda `x = 20`, `y = H - box_h - 20`.
*   **Guardado Directo:** Se guarda el archivo PNG modificado con la firma incrustada antes de que MoviePy lo compile en el videoclip.

---

## Nuevos Parámetros y API de Sincronización

### `ejecutar_proceso_automatizacion`
Se han propagado los siguientes argumentos:
*   `firma_docente` *(str | None)*: Si se deja vacío (`""` o `None`), la firma se desactiva por completo.
*   `posicion_firma` *(str)*: `"derecha"` (por defecto) o `"izquierda"`.
*   `font_size` *(int)*: Tamaño de letra para la tipografía Arial (rango 20 a 80, por defecto 36).
*   `padding` *(int)*: Grosor del recuadro negro (rango 10 a 120, por defecto 30).

### Controles de Interfaz (`app.py`)
En el Paso 2 de Ajustes, se implementó un diseño de dos subcolumnas para regular la cobertura:
```python
font_size = st.slider("Letra:", min_value=20, max_value=80, value=36, step=2)
padding = st.slider("Grosor (Padding):", min_value=10, max_value=120, value=30, step=2)
```

---

## 🛠️ Diagnóstico de Fuentes y Depuración de Interfaz

### El Desafío de la Carga de Fuentes
Si `Arial.ttf` no es localizado por la biblioteca Pillow en el servidor, el sistema realiza una caída de seguridad silenciosa (*fallback*) al tipo de letra por defecto del sistema (`ImageFont.load_default()`). Esta fuente es de mapa de bits y tiene un tamaño de pixel **fijo (no escalable)**, lo que causaba que el control deslizante de "Letra" no hiciera crecer el texto del cartel, mientras que el cartel sí aumentaba por el grosor del padding.

### Soluciones de Diagnóstico Implementadas (Julio 2026):
1. **Caja de Estado en la UI (Streamlit):**
   Se ha agregado un control visual interactivo en la vista previa del archivo. Al subir tu PDF y escribir la firma, verás una alerta:
   * 🟢 **Verde (Éxito):** *"🔍 Fuente Arial.ttf detectada en el servidor (Tamaño de letra: Xpx, Grosor: Ypx)"*. Confirma que el motor TrueType cargó la tipografía correctamente y las letras crecerán al mover el slider.
   * 🔴 **Rojo (Fallo):** *"⚠️ ¡Atención! No se encontró Arial.ttf en <ruta_servidor>. La firma usará la fuente por defecto (no escalable)"*. Alerta de que el archivo `Arial.ttf` no está en la raíz del entorno.
2. **Volcado Inmediato de Logs (`flush=True`):**
   Las impresiones en la consola de `automatizador.py` ahora tienen el flag `flush=True` para forzar que los mensajes de estado del motor de imágenes se impriman en el servidor Streamlit en tiempo real sin almacenamiento en búfer.

---

## 🚀 Actualizaciones de Compatibilidad para Streamlit 1.50+

En la versión de Streamlit `1.50.0` y posteriores, el parámetro `use_column_width=True` fue marcado como deprecado y arrojaba advertencias molestas en la consola del servidor. 

Se ha migrado de forma quirúrgica a la propiedad estándar moderna de Streamlit:
```python
st.image(preview_img_path, caption="...", use_container_width=True)
```
Esto silencia por completo el warning y asegura la compatibilidad a largo plazo de la interfaz de usuario en la nube.

---

## Pautas para Futuras Modificaciones

Si en el futuro se desea:
1.  **Cambiar el Color de Fondo o de Fuente:** Modificar los parámetros `boxcolor` (RGBA) y `fill` (RGBA) dentro de `aplicar_firma_a_slide()` en `automatizador.py`.
2.  **Añadir Bordes Redondeados:** Se puede sustituir `ImageDraw.Draw.text()` / `badge` por una caja con bordes redondeados usando `draw_badge.rounded_rectangle()` de Pillow.
3.  **Sincronizar en la Nube:** Al modificar este proyecto localmente, siempre realizar un `commit` y un `push` al origen remoto de GitHub (`https://github.com/otrabad/automatizador-videos-clases`) para que Streamlit Community Cloud actualice la versión en vivo. Asegurar que los archivos `app.py`, `automatizador.py` y `Arial.ttf` se suban juntos.
