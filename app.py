import streamlit as st
import os
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
    pdf_file = st.file_uploader("Diapositivas (PDF):", type=["pdf"])
with col2:
    txt_file = st.file_uploader("Guion de Voz (TXT):", type=["txt"])

# --- Paso 2: Panel de validacion (se muestra en cuanto ambos archivos estan cargados) ---
reporte_previo = None
if pdf_file and txt_file:
    st.markdown("---")
    reporte_previo = mostrar_panel_validacion(pdf_file.getvalue(), txt_file.getvalue())
    st.markdown("---")

# --- Paso 3: Ajustes de locucion ---
st.subheader("⚙️ 2. Ajustes de Locución y Firma")

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

api_key_input = st.text_input(
    "Clave API de Gemini (opcional — mejora la lectura de abreviaturas médicas):",
    value=st.session_state.api_key,
    type="password",
    help="Generala en https://aistudio.google.com/app/apikey · Si no la ingresás, se usa el texto del guión sin optimización."
)
if api_key_input:
    st.session_state.api_key = api_key_input

# --- Paso 4: Generacion ---
st.subheader("🚀 3. Generar Video")

# Deshabilitar el boton si hay locuciones huerfanas
tiene_huerfanas = reporte_previo is not None and len(reporte_previo["locuciones_huerfanas"]) > 0
archivos_ok     = pdf_file is not None and txt_file is not None

if tiene_huerfanas:
    st.error(
        "No es posible generar el video: corregí las locuciones huérfanas en el guión antes de continuar."
    )

boton_deshabilitado = not archivos_ok or tiene_huerfanas

if st.button("🎬 Generar Video MP4 de la Clase", disabled=boton_deshabilitado):
    pdf_temp  = os.path.join(WORK_DIR, "temp_diapositivas_subidas.pdf")
    txt_temp  = os.path.join(WORK_DIR, "temp_guion_subido.txt")
    video_out = os.path.join(WORK_DIR, "clase_generada.mp4")

    with open(pdf_temp, "wb") as f:
        f.write(pdf_file.getbuffer())
    with open(txt_temp, "wb") as f:
        f.write(txt_file.getbuffer())

    status_box   = st.info("Inicializando el motor de video...")
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
            posicion_firma=posicion_firma
        )

        st.success("🎉 Video compilado con éxito!")

        # Resumen final del proceso
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
    finally:
        for tmp in [pdf_temp, txt_temp]:
            if os.path.exists(tmp):
                os.remove(tmp)
