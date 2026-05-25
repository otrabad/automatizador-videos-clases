import os
import re
import json
import asyncio
import sys
import shutil
import fitz  # PyMuPDF
import edge_tts
from google import genai
from google.genai.errors import APIError
from moviepy import ImageClip, AudioFileClip, concatenate_videoclips, concatenate_audioclips

# Directorio del script y carpeta temporal para guardar archivos intermedios
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TEMP_DIR = os.path.join(SCRIPT_DIR, "temp_assets")

def obtener_ruta_absoluta(ruta):
    """Devuelve la ruta absoluta si ya lo es, o la resuelve relativa al directorio del script."""
    if not ruta:
        return ""
    if os.path.isabs(ruta):
        return ruta
    return os.path.abspath(os.path.join(SCRIPT_DIR, ruta))

def run_async(coro):
    """Ejecuta una corrutina de forma síncrona, manejando si ya hay un bucle de eventos corriendo."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(asyncio.run, coro)
            return future.result()
    else:
        return asyncio.run(coro)

def cargar_configuracion():
    """Carga la configuración desde config.json o usa valores por defecto."""
    config_path = os.path.join(SCRIPT_DIR, "config.json")
    if os.path.exists(config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {
        "pdf_entrada": "diapositivas.pdf",
        "guion_entrada": "guion.txt",
        "video_salida": "clase_final.mp4",
        "voz": "es-ES-AlvaroNeural",
        "optimizar_con_gemini": True,
        "modelo_gemini": "gemini-2.5-flash"
    }

def limpiar_carpeta_temporal():
    """Crea o limpia la carpeta temporal."""
    if os.path.exists(TEMP_DIR):
        shutil.rmtree(TEMP_DIR)
    os.makedirs(TEMP_DIR)

def extraer_diapositivas_pdf(pdf_path):
    """Convierte las páginas de un PDF en imágenes PNG individuales."""
    print(f"[*] Abriendo presentación PDF: {pdf_path}")
    if not os.path.exists(pdf_path):
        print(f"[!] Error: No se encontró el archivo PDF en {pdf_path}")
        sys.exit(1)
        
    doc = fitz.open(pdf_path)
    total_paginas = len(doc)
    print(f"[*] Se detectaron {total_paginas} páginas. Convirtiendo a imágenes...")
    
    for i, pagina in enumerate(doc):
        # pixmap con DPI alto para buena resolución en el video
        pix = pagina.get_pixmap(dpi=150)
        imagen_path = os.path.join(TEMP_DIR, f"slide_{i+1:03d}.png")
        pix.save(imagen_path)
        print(f"    -> Guardada diapositiva {i+1}/{total_paginas} en {imagen_path}")
        
    return total_paginas

def procesar_guion_texto(guion_path, total_paginas):
    """
    Lee un archivo de guion de texto estructurado y lo divide por diapositivas.
    Soporta formatos como: Diapositiva X, [Diapositiva X], Slide X, [Slide X] al inicio de la línea.
    """
    print(f"[*] Leyendo archivo de guion: {guion_path}")
    if not os.path.exists(guion_path):
        print(f"[!] Error: No se encontró el archivo de guion en {guion_path}")
        sys.exit(1)
        
    with open(guion_path, "r", encoding="utf-8") as f:
        lineas = f.readlines()
        
    guion_por_slide = {}
    slide_actual = None
    texto_acumulado = []
    
    # Expresión regular robusta para identificar líneas de diapositivas
    patron_slide = re.compile(r'^\s*\[?(?:Slide|Diapositiva)\s*(\d+)\]?\s*:?\s*(?:\"|“)?', re.IGNORECASE)
    
    for linea in lineas:
        linea_stripped = linea.strip()
        match = patron_slide.match(linea_stripped)
        if match:
            # Guardar el texto acumulado del slide anterior
            if slide_actual is not None:
                texto_final = " ".join(texto_acumulado)
                guion_por_slide[slide_actual] = limpiar_texto_locucion(texto_final)
            
            # Identificar el número de slide
            num_slide = int(match.group(1))
            slide_actual = num_slide
            
            # Extraer el texto restante de esta misma línea
            resto = linea_stripped[match.end():].strip()
            texto_acumulado = [resto] if resto else []
        else:
            if slide_actual is not None:
                texto_acumulado.append(linea_stripped)
                
    # Guardar el último slide
    if slide_actual is not None:
        texto_final = " ".join(texto_acumulado)
        guion_por_slide[slide_actual] = limpiar_texto_locucion(texto_final)
        
    # Completar con vacío las diapositivas que falten
    for i in range(1, total_paginas + 1):
        if i not in guion_por_slide:
            print(f"[!] Advertencia: La diapositiva {i} no tiene guion de voz asignado. Se mostrará en silencio.")
            guion_por_slide[i] = ""
            
    return guion_por_slide

def limpiar_texto_locucion(texto):
    """Limpia etiquetas administrativas y comillas del guion hablado."""
    # Eliminar etiquetas como "Guión de Locución (Audio):" o "Audio:" al inicio del texto
    texto = re.sub(r'^\s*(?:Guión\s+de\s+Locución\s*\(Audio\)\s*:?\s*|Guion\s+de\s+locución\s*:?\s*|Audio\s*:?\s*|Locución\s*:?\s*)', '', texto, flags=re.IGNORECASE)
    
    # Limpiar comillas iniciales y finales sobrantes (incluyendo comillas curvadas de editores de texto)
    texto = texto.strip()
    if (texto.startswith('"') and texto.endswith('"')) or (texto.startswith('“') and texto.endswith('”')):
        texto = texto[1:-1].strip()
    return texto

def optimizar_texto_con_gemini(texto, model_name):
    """Utiliza Gemini para corregir fonética, abreviaturas y disonancias en el guion."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("[!] Advertencia: GEMINI_API_KEY no configurada. Saltando optimización fonética por IA.")
        return texto
        
    try:
        client = genai.Client()
        prompt = (
            "Eres un experto en locución y redacción académica. Tu tarea es optimizar el siguiente texto "
            "para que sea leído por un sistema de síntesis de voz (Text-to-Speech) de forma fluida y natural.\n\n"
            "REGLAS DE OPTIMIZACIÓN:\n"
            "1. Expande cualquier abreviatura, sigla médica, símbolo o expresión científica a su pronunciación hablada natural en español.\n"
            "   Ejemplos:\n"
            "   - 'ABO/Rh' -> 'A B O y R H'\n"
            "   - 'pH' -> 'pe hache'\n"
            "   - 'mg/dl' -> 'miligramos por decilitro'\n"
            "   - 'vs.' -> 'versus'\n"
            "   - '/' -> ' y ' o 'barra' (según el contexto del texto)\n"
            "   - '&' -> 'y'\n"
            "   - '1/2' -> 'un medio' o 'la mitad'\n"
            "2. Mantén el tono académico e instructivo original del texto.\n"
            "3. No agregues introducciones, preámbulos ni comentarios adicionales. Devuelve ÚNICAMENTE el texto optimizado resultante.\n\n"
            f"Texto a optimizar:\n{texto}"
        )
        response = client.models.generate_content(
            model=model_name,
            contents=prompt,
        )
        texto_optimizado = response.text.strip()
        return texto_optimizado
    except Exception as e:
        print(f"[!] Error al invocar la API de Gemini: {e}. Se usará el texto original.")
        return texto

async def generar_audio_diapositiva(texto, voz, output_path):
    """Genera el audio en MP3 usando edge-tts."""
    if not texto:
        # Generar silencio si no hay texto (usaremos ffmpeg o crearemos un audio vacío de 2 segundos)
        # Para simplificar con edge-tts, diremos una pausa vacía
        texto = "..." 
        
    communicate = edge_tts.Communicate(texto, voz)
    await communicate.save(output_path)

async def generar_todos_los_audios(guion_por_slide, voz, optimizar_ia, modelo_gemini):
    """Itera y genera los archivos de audio MP3 para cada diapositiva."""
    print("[*] Iniciando generación de locuciones de voz neural...")
    
    for num_slide, texto in sorted(guion_por_slide.items()):
        if not texto.strip():
            print(f"    -> Diapositiva {num_slide}: Sin guion (Se mostrará en silencio)")
            continue
            
        texto_procesado = texto
        if optimizar_ia:
            print(f"    -> Optimizando texto de diapositiva {num_slide} con Gemini...")
            texto_procesado = optimizar_texto_con_gemini(texto, modelo_gemini)
            print(f"       Texto final: \"{texto_procesado}\"")
            
        output_audio = os.path.join(TEMP_DIR, f"audio_{num_slide:03d}.mp3")
        await generar_audio_diapositiva(texto_procesado, voz, output_audio)
        print(f"    -> Diapositiva {num_slide}: Audio de voz generado en {output_audio}")

def ensamblar_video_final(total_slides, video_salida):
    """Une las imágenes de las diapositivas con sus respectivos audios y las concatena en el video final."""
    print("[*] Iniciando ensamblado de video con MoviePy...")
    video_clips = []
    audio_clips = []
    
    for i in range(1, total_slides + 1):
        imagen_path = os.path.join(TEMP_DIR, f"slide_{i:03d}.png")
        audio_path = os.path.join(TEMP_DIR, f"audio_{i:03d}.mp3")
        
        if not os.path.exists(imagen_path):
            print(f"[!] Error: Falta la imagen para la diapositiva {i} ({imagen_path})")
            continue
            
        if os.path.exists(audio_path):
            print(f"    -> Procesando Diapositiva {i}/{total_slides} (Con audio)")
            audio_clip = AudioFileClip(audio_path)
            # Crear clip de video con la duración del audio
            video_clip = ImageClip(imagen_path).with_duration(audio_clip.duration)
            
            video_clips.append(video_clip)
            audio_clips.append(audio_clip)
        else:
            print(f"    -> Procesando Diapositiva {i}/{total_slides} (En silencio, 2.0s)")
            video_clip = ImageClip(imagen_path).with_duration(2.0)
            video_clips.append(video_clip)
            
    print("[*] Concatenando todas las diapositivas de video...")
    video_final = concatenate_videoclips(video_clips, method="chain")
    
    if audio_clips:
        print("[*] Concatenando pistas de audio...")
        audio_final = concatenate_audioclips(audio_clips)
        print("[*] Acoplando pista de audio final al video...")
        video_final = video_final.with_audio(audio_final)
        
    print("[*] Renderizando archivo MP4 final...")
    # Exportar el video final con configuraciones estándar compatibles con Moodle
    video_final.write_videofile(
        video_salida, 
        fps=2, 
        codec="libx264", 
        preset="ultrafast",
        audio_codec="aac",
        temp_audiofile=os.path.join(TEMP_DIR, "temp_audio_final.m4a"),
        remove_temp=True
    )
    
    # Cerrar todos los clips para liberar memoria
    for clip in video_clips:
        clip.close()
    for clip in audio_clips:
        clip.close()
    if audio_clips:
        audio_final.close()
    video_final.close()
    
    print(f"[+] ¡Éxito! El video final se ha generado correctamente en: {video_salida}")

def ejecutar_proceso_automatizacion(pdf_path, guion_path, video_salida, voz, optimizar_ia, modelo_gemini="gemini-2.5-flash", api_key=None, callback_progreso=None):
    """
    Ejecuta todo el flujo de trabajo de automatización de video.
    Permite pasar variables de forma dinámica y proporciona callbacks de progreso para interfaces.
    """
    if api_key:
        os.environ["GEMINI_API_KEY"] = api_key
        
    limpiar_carpeta_temporal()
    
    if callback_progreso:
        callback_progreso("Extrayendo diapositivas del PDF...", 0.1)
        
    total_paginas = extraer_diapositivas_pdf(pdf_path)
    
    if callback_progreso:
        callback_progreso("Procesando y validando guion de voz...", 0.3)
        
    guion_por_slide = procesar_guion_texto(guion_path, total_paginas)
    
    if callback_progreso:
        callback_progreso("Generando locuciones con voz neural...", 0.5)
        
    run_async(generar_todos_los_audios(
        guion_por_slide, 
        voz, 
        optimizar_ia,
        modelo_gemini
    ))
    
    if callback_progreso:
        callback_progreso("Sincronizando y renderizando video final...", 0.8)
        
    ensamblar_video_final(total_paginas, video_salida)
    
    # Conservar el video, pero limpiar archivos temporales
    if os.path.exists(TEMP_DIR):
        shutil.rmtree(TEMP_DIR)
        
    if callback_progreso:
        callback_progreso("¡Video finalizado con éxito!", 1.0)

def main():
    print("="*60)
    print("   AUTOMATIZADOR DE VIDEOS PARA CLASES ASINCRÓNICAS (MOODLE)")
    print("="*60)
    
    config = cargar_configuracion()
    
    pdf_entrada = obtener_ruta_absoluta(config.get('pdf_entrada', 'diapositivas.pdf'))
    guion_entrada = obtener_ruta_absoluta(config.get('guion_entrada', 'guion.txt'))
    video_salida = obtener_ruta_absoluta(config.get('video_salida', 'clase_final.mp4'))
    
    # Imprimir configuración
    print(f"[*] Archivo PDF: {pdf_entrada}")
    print(f"[*] Archivo Guion: {guion_entrada}")
    print(f"[*] Video Salida: {video_salida}")
    print(f"[*] Voz seleccionada: {config['voz']}")
    print(f"[*] Optimización por Gemini IA: {'SÍ' if config['optimizar_con_gemini'] else 'NO'}")
    print("-"*60)
    
    # Iniciar proceso
    limpiar_carpeta_temporal()
    
    # 1. Extraer imágenes del PDF
    total_paginas = extraer_diapositivas_pdf(pdf_entrada)
    
    # 2. Procesar el archivo de guion
    guion_por_slide = procesar_guion_texto(guion_entrada, total_paginas)
    
    # 3. Generar las locuciones de voz (TTS)
    run_async(generar_todos_los_audios(
        guion_por_slide, 
        config['voz'], 
        config['optimizar_con_gemini'],
        config['modelo_gemini']
    ))
    
    # 4. Ensamblar todo en el MP4 final
    ensamblar_video_final(total_paginas, video_salida)
    
    # 5. Limpieza final (Opcional)
    # Si quieres conservar los archivos temporales para depurar, comenta la línea de abajo
    if os.path.exists(TEMP_DIR):
        shutil.rmtree(TEMP_DIR)
        print("[*] Carpeta temporal limpia.")
        
    print("="*60)
    print("   PROCESO TERMINADO CON ÉXITO")
    print("="*60)

if __name__ == "__main__":
    main()
