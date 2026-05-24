import streamlit as st
import os
import shutil
import asyncio
from automatizador import ejecutar_proceso_automatizacion

# Configuración de la página
st.set_page_config(page_title="Automatizador de Videos para Clases Moodle", page_icon="🎬", layout="centered")

# Estilos CSS personalizados para una estética premium y moderna (Modo Oscuro)
st.markdown("""
    <style>
    /* Estilos generales */
    .stApp {
        background: linear-gradient(135deg, #0e1117 0%, #171d26 100%);
        color: #f0f2f6;
    }
    
    /* Títulos con degradado */
    h1 {
        font-family: 'Outfit', 'Inter', sans-serif;
        font-weight: 800;
        background: linear-gradient(90deg, #ff4b4b, #ffa1a1);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        text-align: center;
        margin-bottom: 25px;
    }
    
    /* Contenedores con efecto de vidrio */
    div.stBlock {
        background-color: rgba(255, 255, 255, 0.02) !important;
        border-radius: 12px !important;
        padding: 20px !important;
        border: 1px solid rgba(255, 255, 255, 0.04) !important;
        margin-bottom: 15px;
    }
    
    /* Botón premium de generación */
    .stButton>button {
        background: linear-gradient(90deg, #ff4b4b 0%, #ff6b6b 100%) !important;
        color: white !important;
        font-weight: bold !important;
        border-radius: 20px !important;
        border: none !important;
        padding: 12px 30px !important;
        font-size: 16px !important;
        transition: all 0.3s ease !important;
        box-shadow: 0 4px 15px rgba(255, 75, 75, 0.25) !important;
        width: 100%;
        margin-top: 15px;
    }
    .stButton>button:hover {
        transform: translateY(-2px) !important;
        box-shadow: 0 6px 20px rgba(255, 75, 75, 0.45) !important;
    }
    </style>
""", unsafe_allow_html=True)

st.title("🎬 Automatizador de Clases Virtuales")
st.write("Diseñado para crear videos MP4 educativos listos para Moodle a partir de tus diapositivas (PDF) y tu guion de texto (TXT).")

# Directorio de trabajo local
WORK_DIR = os.path.dirname(os.path.abspath(__file__))

# Mantener la clave de API en memoria de sesión de forma segura
if 'api_key' not in st.session_state:
    st.session_state.api_key = ""

# Formulario principal de carga
st.subheader("📁 1. Cargar Materiales")
col1, col2 = st.columns(2)

with col1:
    pdf_file = st.file_uploader("Subir Diapositivas (PDF):", type=["pdf"], help="Carga tu presentación de diapositivas exportada en PDF.")
with col2:
    txt_file = st.file_uploader("Subir Guion de Voz (TXT):", type=["txt"], help="Carga el guion de texto dividido por marcas 'Diapositiva X'.")

st.subheader("⚙️ 2. Ajustes de Locución")

# Voces disponibles organizadas de forma amigable
opciones_voces = {
    "Español España - Álvaro (Voz Masculina)": "es-ES-AlvaroNeural",
    "Español España - Elvira (Voz Femenina)": "es-ES-ElviraNeural",
    "Español México - Jorge (Voz Masculina)": "es-MX-JorgeNeural",
    "Español México - Dalia (Voz Femenina)": "es-MX-DaliaNeural",
    "Español Argentina - Tomás (Voz Masculina)": "es-AR-TomasNeural",
    "Español Argentina - Elena (Voz Femenina)": "es-AR-ElenaNeural",
}

voz_seleccionada_label = st.selectbox(
    "Seleccionar voz para la narración:", 
    options=list(opciones_voces.keys()),
    index=0
)
voz = opciones_voces[voz_seleccionada_label]

# Entrada interactiva para la API Key de Gemini
api_key_input = st.text_input(
    "Clave de API de Gemini (Opcional - Para optimizar lecturas técnicas y abreviaturas):",
    value=st.session_state.api_key,
    type="password",
    help="Si introduces tu clave, Gemini reescribirá automáticamente abreviaturas como 'ABO/Rh' a 'ABO y Rh' para una locución más fluida."
)
if api_key_input:
    st.session_state.api_key = api_key_input

# Botón para iniciar el proceso de renderizado
if st.button("🚀 Generar Video MP4 de la Clase"):
    if not pdf_file or not txt_file:
        st.error("⚠️ Error: Debes cargar tanto el archivo PDF de diapositivas como el guion de texto TXT.")
    else:
        # Rutas de archivos de procesamiento temporal
        pdf_temp_path = os.path.join(WORK_DIR, "temp_diapositivas_subidas.pdf")
        txt_temp_path = os.path.join(WORK_DIR, "temp_guion_subido.txt")
        video_final_path = os.path.join(WORK_DIR, "clase_generada.mp4")
        
        # Escribir los contenidos subidos a disco temporalmente
        with open(pdf_temp_path, "wb") as f:
            f.write(pdf_file.getbuffer())
        with open(txt_temp_path, "wb") as f:
            f.write(txt_file.getbuffer())
            
        # Widgets visuales para el seguimiento del progreso en tiempo real
        status_box = st.info("Inicializando el motor de video...")
        progress_bar = st.progress(0.0)
        
        # Callback que el backend ejecutará para actualizar la web de Streamlit
        def actualizar_progreso(mensaje, valor):
            status_box.info(mensaje)
            progress_bar.progress(valor)
            
        try:
            # Ejecutar el flujo de renderizado adaptado
            ejecutar_proceso_automatizacion(
                pdf_path=pdf_temp_path,
                guion_path=txt_temp_path,
                video_salida=video_final_path,
                voz=voz,
                optimizar_ia=bool(st.session_state.api_key),
                modelo_gemini="gemini-2.5-flash",
                api_key=st.session_state.api_key if st.session_state.api_key else None,
                callback_progreso=actualizar_progreso
            )
            
            # Éxito y visualización
            st.success("🎉 ¡Video de la clase compilado con éxito!")
            
            # Cargar y reproducir el video generado
            with open(video_final_path, "rb") as video_file:
                video_bytes = video_file.read()
                st.video(video_bytes)
                
            # Botón para descargar el archivo directamente
            st.download_button(
                label="📥 Descargar Video de la Clase (MP4)",
                data=video_bytes,
                file_name="clase_video_final.mp4",
                mime="video/mp4"
            )
            
        except Exception as e:
            st.error(f"❌ Ocurrió un error inesperado: {e}")
            st.info("Consejo: Asegúrate de que las marcas de diapositiva en tu guion comiencen exactamente con 'Diapositiva X' y que el número de diapositivas coincida con las páginas del PDF.")
            
        finally:
            # Limpiar los archivos temporales subidos para no dejar residuos
            if os.path.exists(pdf_temp_path):
                os.remove(pdf_temp_path)
            if os.path.exists(txt_temp_path):
                os.remove(txt_temp_path)
