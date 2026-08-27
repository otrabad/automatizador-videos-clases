import streamlit as st
import os
import tempfile
import fitz          # PyMuPDF — para pre-validar el PDF sin procesar
import re
from automatizador import (
    ejecutar_proceso_automatizacion,
    validar_coincidencia,
    procesar_guion_texto,
)

# ---------------------------------------------------------------------------
# Configuracion de pagina
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Automatizador de Videos para Clases Moodle",
    page_icon="🎬",
    layout="centered"
)

st.markdown("""
    <style>
    .stApp { background: linear-gradient(135deg, #0e1117 0%, #171d26 100%); color: #f0f2f6; }
    h1 {
        font-family: 'Outfit', 'Inter', sans-serif; font-weight: 800;
        background: linear-gradient(90deg, #ff4b4b, #ffa1a1);
        -webkit-background-clip: text; -webkit-text-fill-color: transparent;
        text-align: center; margin-bottom: 25px;
    }
    .stButton>button {
        background: linear-gradient(90deg, #ff4b4b 0%, #ff6b6b 100%) !important;
        color: white !important; font-weight: bold !important;
        border-radius: 20px !important; border: none !important;
        padding: 12px 30px !important; font-size: 16px !important;
        transition: all 0.3s ease !important;
        box-shadow: 0 4px 15px rgba(255,75,75,0.25) !important; width: 100%; margin-top: 15px;
    }
    .stButton>button:hover { transform: translateY(-2px) !important; box-shadow: 0 6px 20px rgba(255,75,75,0.45) !important; }
    .validacion-ok    { background:#0d2b1e; border:1px solid #10b981; border-radius:8px; padding:12px 16px; margin:4px 0; }
    .validacion-warn  { background:#2b2008; border:1px solid #f59e0b; border-radius:8px; padding:12px 16px; margin:4px 0; }
    .validacion-error { background:#2b0d0d; border:1px solid #ef4444; border-radius:8px; padding:12px 16px; margin:4px 0; }
    </style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Estado de sesion
# ---------------------------------------------------------------------------
if "api_key" not in st.session_state:
    st.session_state.api_key = ""

WORK_DIR = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------------------
# Helpers de pre-validacion (sin generar nada, solo para mostrar el panel)
# ---------------------------------------------------------------------------

def contar_paginas_pdf(pdf_bytes):
    """Cuenta las paginas del PDF sin guardarlo en disco."""
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    return len(doc)

def parsear_guion_desde_bytes(txt_bytes, total_paginas):
    """Parsea el guion desde bytes para el panel de validacion previo."""
    patron_slide = re.compile(r'^\s*\[?(?:Slide|Diapositiva)\s*(\d+)\]?\s*:?\s*(?:\"|")?', re.IGNORECASE)
    lineas = txt_bytes.decode("utf-8", errors="replace").splitlines()
    guion = {}
    slide_actual = None
    acumulado = []
    for linea in lineas:
        ls = linea.strip()
        m = patron_slide.match(ls)
        if m:
            if slide_actual is not None:
                guion[slide_actual] = " ".join(acumulado).strip()
            slide_actual = int(m.group(1))
            resto = ls[m.end():].strip()
            acumulado = [resto] if resto else []
        else:
            if slide_actual is not None:
                acumulado.append(ls)
    if slide_actual is not None:
        guion[slide_actual] = " ".join(acumulado).strip()
    return guion

def mostrar_panel_validacion(pdf_bytes, txt_bytes):
    """
    Muestra el panel de validacion de coincidencia PDF <-> Guion.
    Retorna el reporte para que la logica principal decida si habilitar la generacion.
    """
    try:
        total_paginas   = contar_paginas_pdf(pdf_bytes)
        guion_por_slide = parsear_guion_desde_bytes(txt_bytes, total_paginas)
        reporte         = validar_coincidencia(total_paginas, guion_por_slide)
    except Exception as e:
        st.error(f"Error al pre-validar los archivos: {e}")
        return None

    st.subheader("🔍 Validacion de coincidencia PDF ↔ Guion")

    col1, col2, col3 = st.columns(3)
    col1.metric("Diapositivas en PDF",   reporte["total_slides"])
    col2.metric("Locuciones en guion",   reporte["total_locuciones"])
    col3.metric("Slides con voz",        len(reporte["slides_con_voz"]))

    # Slides con voz
    if reporte["slides_con_voz"]:
        st.markdown(
            f'<div class="validacion-ok">✅ <strong>Slides con locución asignada:</strong> '
            f'{reporte["slides_con_voz"]}</div>',
            unsafe_allow_html=True
        )

    # Slides sin voz (advertencia, no bloquea)
    if reporte["slides_sin_voz"]:
        st.markdown(
            f'<div class="validacion-warn">⚠️ <strong>Slides SIN locución</strong> '
            f'(quedarán en silencio 2 s): <strong>{reporte["slides_sin_voz"]}</strong><br>'
            f'<small>Si esto no es intencional, revisá el guión y agregá las secciones faltantes.</small></div>',
            unsafe_allow_html=True
        )
    else:
        st.markdown(
            '<div class="validacion-ok">✅ Todos los slides del PDF tienen locución asignada.</div>',
            unsafe_allow_html=True
        )

    # Locuciones huerfanas (bloquea la generacion)
    if reporte["locuciones_huerfanas"]:
        st.markdown(
            f'<div class="validacion-error">❌ <strong>Locuciones HUÉRFANAS</strong> '
            f'(número de slide no existe en el PDF): <strong>{reporte["locuciones_huerfanas"]}</strong><br>'
            f'<small>Estas locuciones NO se narrarán. Corregí la numeración del guión antes de generar el video.</small></div>',
            unsafe_allow_html=True
        )
    else:
        st.markdown(
            '<div class="validacion-ok">✅ Sin locuciones huérfanas — la numeración del guión es consistente con el PDF.</div>',
            unsafe_allow_html=True
        )

    return reporte

# ---------------------------------------------------------------------------
# Interfaz principal
# ---------------------------------------------------------------------------
st.title("🎬 Automatizador de Clases Virtuales")
st.write(
    "Crea videos MP4 educativos listos para Moodle a partir de tus diapositivas (PDF) y tu guion de texto (TXT)."
)

# --- Paso 1: Carga de materiales ---
st.subheader("📁 1. Cargar Materiales")
col1, col2 = st.columns(2)
with col1:
    slide_file = st.file_uploader(
        "Diapositivas (PDF o PowerPoint .pptx):",
        type=["pdf", "pptx", "ppt"],
        help="Subí tu archivo PDF o tu presentación en formato PowerPoint (.pptx / .ppt)."
    )
with col2:
    txt_file = st.file_uploader(
        "Guion de Voz (TXT):",
        type=["txt"],
        help="Subí el guion en formato .txt con etiquetas [Slide 1], [Slide 2], etc."
    )

pdf_file = None
pdf_bytes_para_validacion = None

if slide_file:
    # Si es PPTX o PPT, intentar convertir a PDF
    if slide_file.name.lower().endswith(('.pptx', '.ppt')):
        from automatizador import buscar_ejecutable_libreoffice, convertir_pptx_a_pdf
        exe = buscar_ejecutable_libreoffice()
        if exe:
            with st.spinner("Convertidor automático: Transformando presentación PowerPoint (.pptx) a PDF..."):
                try:
                    with tempfile.TemporaryDirectory() as conv_dir:
                        in_pptx = os.path.join(conv_dir, slide_file.name)
                        with open(in_pptx, "wb") as f:
                            f.write(slide_file.getvalue())
                        out_pdf = convertir_pptx_a_pdf(in_pptx, conv_dir)
                        with open(out_pdf, "rb") as f:
                            pdf_bytes_para_validacion = f.read()
                        pdf_file = slide_file  # Mantener referencia para habilitar UI
                    st.success("✨ Presentación PowerPoint (.pptx) convertida a PDF con éxito.")
                except Exception as e:
                    st.error(f"Error al convertir presentación PowerPoint: {e}")
        else:
            st.warning(
                "💡 **Presentación PowerPoint (.pptx) detectada:**\n"
                "Para procesarla de forma 100% automática en tu computadora local, instalá LibreOffice (`brew install --cask libreoffice`), "
                "o simplemente exportá tu presentación como **PDF** desde PowerPoint (*Archivo > Guardar como > PDF*) y subí el archivo `.pdf`.\n\n"
                "*(Nota: En la versión publicada en la nube esta conversión ocurre automáticamente)*"
            )
    else:
        pdf_file = slide_file
        pdf_bytes_para_validacion = slide_file.getvalue()

# --- Paso 2: Editor interactivo de guion y Panel de validacion ---
reporte_previo = None
guion_texto_actual = ""

if txt_file:
    # Cargar contenido inicial del TXT subido si cambio de archivo o no esta en session_state
    contenido_subido = txt_file.getvalue().decode("utf-8", errors="replace")
    if "last_uploaded_txt_name" not in st.session_state or st.session_state.last_uploaded_txt_name != txt_file.name:
        st.session_state.last_uploaded_txt_name = txt_file.name
        st.session_state.guion_editable = contenido_subido
    elif "guion_editable" not in st.session_state:
        st.session_state.guion_editable = contenido_subido

if pdf_file and txt_file:
    st.markdown("---")
    st.subheader("✏️ Editor e Inspección Interactiva del Guion")
    st.info("Podés editar o corregir la numeración [Slide X] de tu guión directamente aquí sin necesidad de re-subir el archivo:")

    guion_texto_actual = st.text_area(
        "Contenido del guion (editable en vivo):",
        value=st.session_state.get("guion_editable", ""),
        height=220,
        help="Editá el texto o las marcas [Slide X] para corregir la alineación con el PDF antes de generar el video."
    )
    st.session_state.guion_editable = guion_texto_actual

    if pdf_bytes_para_validacion:
        reporte_previo = mostrar_panel_validacion(pdf_bytes_para_validacion, guion_texto_actual.encode("utf-8"))
    st.markdown("---")

# --- Paso 3: Ajustes de locucion y personalizacion ---
st.subheader("⚙️ 2. Ajustes de Locución, Ritmo y Firma")

col_voz, col_firma = st.columns(2)

with col_voz:
    opciones_voces = {
        "Español Argentina - Tomás (Masculina)": "es-AR-TomasNeural",
        "Español Argentina - Elena (Femenina)":  "es-AR-ElenaNeural",
        "Español España - Álvaro (Masculina)":   "es-ES-AlvaroNeural",
        "Español España - Elvira (Femenina)":    "es-ES-ElviraNeural",
        "Español México - Jorge (Masculina)":    "es-MX-JorgeNeural",
        "Español México - Dalia (Femenina)":     "es-MX-DaliaNeural",
    }
    voz_label = st.selectbox("Voz para la narración:", options=list(opciones_voces.keys()), index=0)
    voz = opciones_voces[voz_label]

    sub_voz1, sub_voz2 = st.columns(2)
    with sub_voz1:
        opciones_ritmo = {
            "Lento (-10%)": "-10%",
            "Normal (+0%)": "+0%",
            "Rápido (+10%)": "+10%",
            "Muy rápido (+20%)": "+20%"
        }
        ritmo_label = st.selectbox("Ritmo de locución:", options=list(opciones_ritmo.keys()), index=1)
        rate_val = opciones_ritmo[ritmo_label]
    with sub_voz2:
        opciones_pausa = {
            "Sin pausa (0 s)": 0.0,
            "Pausa breve (0.5 s)": 0.5,
            "Pausa media (1.0 s)": 1.0,
            "Pausa prolongada (1.5 s)": 1.5
        }
        pausa_label = st.selectbox("Pausa entre slides:", options=list(opciones_pausa.keys()), index=1)
        pausa_val = opciones_pausa[pausa_label]

with col_firma:
    firma_docente = st.text_input(
        "Texto / Firma opcional (vacío para desactivar):",
        value="",
        placeholder="Ej: Dr. Omar Trabadelo o cualquier frase",
        help="Si escribís un texto, se colocará sobre un fondo negro sólido para cubrir marcas de agua anteriores en las diapositivas. Si lo dejás vacío, no se colocará nada."
    )
    posicion_firma = st.selectbox(
        "Posición de la firma (visto de frente):",
        options=["Derecha", "Izquierda"],
        index=0
    ).lower()

    st.markdown("<small style='color: #ff4b4b; font-weight: bold;'>📐 Ajustes de Cobertura:</small>", unsafe_allow_html=True)
    sub_col1, sub_col2 = st.columns(2)
    with sub_col1:
        font_size = st.slider("Letra:", min_value=20, max_value=80, value=36, step=2, help="Aumenta el tamaño de la tipografía.")
    with sub_col2:
        padding = st.slider("Grosor (Padding):", min_value=10, max_value=120, value=30, step=2, help="Aumenta el margen negro alrededor para cubrir logotipos gigantes.")

# --- Seccion de IA Gemini ---
col_ai1, col_ai2 = st.columns(2)
with col_ai1:
    api_key_input = st.text_input(
        "Clave API de Gemini (opcional — optimización IA):",
        value=st.session_state.api_key,
        type="password",
        help="Generala en https://aistudio.google.com/app/apikey · Si no la ingresás, se usa el texto del guión sin optimización."
    )
    if api_key_input:
        st.session_state.api_key = api_key_input
with col_ai2:
    estilo_gemini = st.selectbox(
        "Estilo de optimización con IA:",
        options=["Médico / Académico Formal", "Didáctico / Divulgativo", "Conciso / Breve"],
        index=0,
        help="Define cómo la IA de Gemini reescribe y optimiza la fonética y estilo del guion antes de sintetizar la voz."
    )

# --- Vista Previa en tiempo real de la firma ---
if pdf_file and firma_docente:
    st.markdown("---")
    st.subheader("🖼️ Vista Previa en Tiempo Real (Página 1)")
    with st.spinner("Generando vista previa interactiva..."):
        try:
            with tempfile.TemporaryDirectory() as preview_temp_dir:
                preview_pdf_path = os.path.join(preview_temp_dir, "preview_in.pdf")
                with open(preview_pdf_path, "wb") as f:
                    f.write(pdf_bytes_para_validacion)

                doc = fitz.open(preview_pdf_path)
                if len(doc) > 0:
                    pagina = doc[0]
                    pix = pagina.get_pixmap(dpi=120)
                    preview_img_path = os.path.join(preview_temp_dir, "preview_slide.png")
                    pix.save(preview_img_path)

                    from automatizador import aplicar_firma_a_slide

                    font_path_check = os.path.join(WORK_DIR, "Arial.ttf")
                    if os.path.exists(font_path_check):
                        st.success(f"🔍 Fuente Arial.ttf detectada en el servidor (Tamaño de letra: {font_size}px, Grosor: {padding}px)")
                    else:
                        st.error(f"⚠️ ¡Atención! No se encontró Arial.ttf en {font_path_check}. La firma usará la fuente por defecto (no escalable).")

                    aplicar_firma_a_slide(
                        preview_img_path,
                        texto_firma=firma_docente,
                        posicion=posicion_firma,
                        font_size=font_size,
                        padding=padding
                    )

                    st.image(
                        preview_img_path,
                        caption="Vista previa interactiva de la primera diapositiva. ¡Ajustá los controles deslizantes para ver los cambios!",
                        use_container_width=True
                    )
        except Exception as e:
            st.error(f"No se pudo generar la vista previa: {e}")

# --- Paso 4: Generacion ---
st.subheader("🚀 3. Generar Video")

tiene_huerfanas = reporte_previo is not None and len(reporte_previo["locuciones_huerfanas"]) > 0
archivos_ok     = pdf_file is not None and txt_file is not None

if tiene_huerfanas:
    st.error(
        "No es posible generar el video: corregí las locuciones huérfanas en el guión antes de continuar."
    )
elif not archivos_ok:
    if slide_file is not None and pdf_file is None:
        st.error(
            "⚠️ El botón de generar está deshabilitado porque no se pudo preparar un PDF a partir del archivo de "
            "diapositivas subido (revisá el aviso más arriba sobre la conversión de PowerPoint). Exportá tu "
            "presentación como PDF y subila para continuar."
        )
    elif slide_file is None:
        st.info("Subí tus diapositivas (PDF o PowerPoint) para habilitar la generación.")
    elif txt_file is None:
        st.info("Subí el guion de voz (TXT) para habilitar la generación.")

boton_deshabilitado = not archivos_ok or tiene_huerfanas

if st.button("🎬 Generar Video MP4 de la Clase", disabled=boton_deshabilitado):
    with tempfile.TemporaryDirectory() as session_temp_dir:
        ext = ".pdf" if not slide_file.name.lower().endswith(('.pptx', '.ppt')) else os.path.splitext(slide_file.name)[1]
        pdf_temp  = os.path.join(session_temp_dir, f"diapositivas{ext}")
        txt_temp  = os.path.join(session_temp_dir, "guion.txt")
        video_out = os.path.join(session_temp_dir, "clase_generada.mp4")

        with open(pdf_temp, "wb") as f:
            if pdf_bytes_para_validacion:
                f.write(pdf_bytes_para_validacion)
            else:
                f.write(slide_file.getbuffer())

        guion_a_usar = guion_texto_actual if guion_texto_actual else txt_file.getvalue().decode("utf-8", errors="replace")
        with open(txt_temp, "w", encoding="utf-8") as f:
            f.write(guion_a_usar)

        status_box   = st.info("Inicializando el motor de video en entorno aislado...")
        progress_bar = st.progress(0.0)

        def actualizar_progreso(mensaje, valor):
            status_box.info(mensaje)
            progress_bar.progress(valor)

        try:
            reporte_final = ejecutar_proceso_automatizacion(
                pdf_path=pdf_temp,
                guion_path=txt_temp,
                video_salida=video_out,
                voz=voz,
                optimizar_ia=bool(st.session_state.api_key),
                modelo_gemini="gemini-2.5-flash",
                api_key=st.session_state.api_key or None,
                callback_progreso=actualizar_progreso,
                firma_docente=firma_docente if firma_docente else None,
                posicion_firma=posicion_firma,
                font_size=font_size,
                padding=padding,
                rate=rate_val,
                pausa_inter_slide=pausa_val,
                estilo_gemini=estilo_gemini,
                temp_dir=session_temp_dir,
                contenido_guion_texto=guion_a_usar
            )

            st.success("🎉 Video compilado con éxito!")

            if reporte_final and reporte_final["slides_sin_voz"]:
                st.warning(
                    f"⚠️ Los slides {reporte_final['slides_sin_voz']} quedaron en silencio "
                    "por no tener locución asignada en el guión."
                )

            with open(video_out, "rb") as vf:
                video_bytes = vf.read()
            st.video(video_bytes)
            st.download_button(
                label="📥 Descargar Video (MP4)",
                data=video_bytes,
                file_name="clase_video_final.mp4",
                mime="video/mp4"
            )

        except Exception as e:
            st.error(f"❌ Error inesperado: {e}")
            st.info(
                "Consejo: verificá que las marcas del guión comiencen exactamente con 'Diapositiva X' "
                "y que la numeración coincida con las páginas del PDF."
            )
