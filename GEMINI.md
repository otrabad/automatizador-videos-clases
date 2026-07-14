# Instrucciones y Memoria de Desarrollo: Cobertura de Marca de Agua Interactiva

Este documento sirve como registro técnico y guía para futuras actualizaciones de la aplicación de automatización de video-clases.

## Descripción de la Funcionalidad

Se ha implementado una característica que permite cubrir marcas de agua anteriores (como logotipos corporativos o texto de plantillas de diapositivas) mediante una caja negra opaca y sólida que superpone un texto personalizado o firma del docente.

### Archivos Modificados
1. **`automatizador.py` (Core):** Aloja el motor de procesamiento de imágenes y ensamblado de MoviePy.
2. **`app.py` (UI Streamlit):** Aloja los controles deslizantes e interactivos de la interfaz web.
3. **`config.json` (Ajustes predeterminados):** Almacena los valores iniciales para ejecuciones por línea de comandos (CLI).

---

## Cómo Funciona la Lógica Interna

### 1. Extracción y Estampado Local (Cero Costo de Procesamiento)
Para evitar la lentitud que supone re-renderizar o codificar videos con FFmpeg al final, la aplicación realiza el estampado **directamente sobre los archivos PNG de las diapositivas extraídas** bajo la carpeta temporal `temp_assets/`.

La función principal encargada de esto es:
```python
def aplicar_firma_a_slide(imagen_path, texto_firma="Dr. Omar Trabadelo", posicion="derecha", font_size=36, padding=30):
```
*   **Pillow (PIL):** Abre cada slide PNG extraído, calcula dinámicamente las dimensiones del texto de la firma utilizando la tipografía Arial del sistema macOS (`/System/Library/Fonts/Supplemental/Arial.ttf` o `/Library/Fonts/Arial.ttf`).
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
En el Paso 2 de Ajustes, se implementó un diseño de dos subcolumnas para evitar sobrecargar el espacio visual:
```python
font_size = st.slider("Letra:", min_value=20, max_value=80, value=36, step=2)
padding = st.slider("Grosor (Padding):", min_value=10, max_value=120, value=30, step=2)
```

---

## Pautas para Futuras Modificaciones

Si en el futuro se desea:
1.  **Cambiar el Color de Fondo o de Fuente:** Modificar los parámetros `boxcolor` (RGBA) y `fill` (RGBA) dentro de `aplicar_firma_a_slide()` en `automatizador.py`.
2.  **Añadir Bordes Redondeados:** Se puede sustituir `ImageDraw.Draw.text()` / `badge` por una caja con bordes redondeados usando `draw_badge.rounded_rectangle()` de Pillow.
3.  **Sincronizar en la Nube:** Al modificar este proyecto localmente, siempre realizar un `commit` y un `push` al origen remoto de GitHub (`https://github.com/otrabad/automatizador-videos-clases`) para que Streamlit Community Cloud actualice la versión en vivo.
