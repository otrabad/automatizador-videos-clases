import os
import re
import json
import asyncio
import sys
import shutil
import struct
import fitz  # PyMuPDF
import edge_tts
from google import genai
from moviepy import ImageClip, AudioFileClip, concatenate_videoclips, concatenate_audioclips

# Directorio del script y carpeta temporal para guardar archivos intermedios
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TEMP_DIR = os.path.join(SCRIPT_DIR, "temp_assets")

# ---------------------------------------------------------------------------
# Utilidades generales
# ---------------------------------------------------------------------------

def obtener_ruta_absoluta(ruta):
    """Devuelve la ruta absoluta; si es relativa, la resuelve desde el directorio del script."""
    if not ruta:
        return ""
    if os.path.isabs(ruta):
        return ruta
    return os.path.abspath(os.path.join(SCRIPT_DIR, ruta))

def run_async(coro):
    """Ejecuta una corrutina de forma sincronica, manejando si ya hay un bucle de eventos corriendo."""
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
    """
    Carga la configuracion desde config.json o usa valores por defecto.

    Variable de entorno para modo CLI:
      GEMINI_API_KEY : clave de Google Gemini (requerida si optimizar_con_gemini=true).
                       Generarla en https://aistudio.google.com/app/apikey
    """
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

# ---------------------------------------------------------------------------
# Paso 1: Extraccion de diapositivas del PDF
# ---------------------------------------------------------------------------

def aplicar_firma_a_slide(imagen_path, texto_firma="Dr. Omar Trabadelo", posicion="derecha"):
    """Dibuja de forma local un cuadro negro con la firma del docente en el slide PNG."""
    from PIL import Image, ImageDraw, ImageFont
    try:
        slide = Image.open(imagen_path)
        W, H = slide.size
        
        font_path = '/System/Library/Fonts/Supplemental/Arial.ttf'
        if not os.path.exists(font_path):
            font_path = '/Library/Fonts/Arial.ttf' # Fallback
            
        font_size = 32
        padding = 25
        
        if os.path.exists(font_path):
            font = ImageFont.truetype(font_path, font_size)
        else:
            font = ImageFont.load_default()
            
        # Calcular tamaño del texto de forma segura
        draw_dummy = ImageDraw.Draw(Image.new('RGB', (1, 1)))
        try:
            bbox = draw_dummy.textbbox((0, 0), texto_firma, font=font)
            text_w = bbox[2] - bbox[0]
            text_h = bbox[3] - bbox[1]
            text_offset_x = bbox[0]
            text_offset_y = bbox[1]
        except AttributeError:
            text_w, text_h = draw_dummy.textsize(texto_firma, font=font)
            text_offset_x, text_offset_y = 0, 0
            
        box_w = text_w + (padding * 2)
        box_h = text_h + (padding * 2)
        
        # Posición derecha o izquierda (vista de frente)
        if posicion == "derecha":
            x = W - box_w - 20
        else:
            x = 20
        y = H - box_h - 20
        
        # Crear la caja de la firma como overlay opaco
        badge = Image.new('RGBA', (box_w, box_h), (0, 0, 0, 255))
        draw_badge = ImageDraw.Draw(badge)
        draw_badge.text((padding - text_offset_x, padding - text_offset_y), texto_firma, font=font, fill=(255, 255, 255, 255))
        
        # Pegar el badge sobre el slide y guardar
        slide.paste(badge, (x, y))
        slide.save(imagen_path)
    except Exception as e:
        print(f"    [!] Error al estampar firma en diapositiva: {e}")

def extraer_diapositivas_pdf(pdf_path, firma_docente=None, posicion_firma="derecha"):
    """Convierte las paginas de un PDF en imagenes PNG individuales."""
    print(f"[*] Abriendo presentacion PDF: {pdf_path}")
    if not os.path.exists(pdf_path):
        print(f"[!] Error: No se encontro el archivo PDF en {pdf_path}")
        sys.exit(1)
    doc = fitz.open(pdf_path)
    total_paginas = len(doc)
    print(f"[*] Se detectaron {total_paginas} paginas. Convirtiendo a imagenes...")
    for i, pagina in enumerate(doc):
        pix = pagina.get_pixmap(dpi=150)
        imagen_path = os.path.join(TEMP_DIR, f"slide_{i+1:03d}.png")
        pix.save(imagen_path)
        if firma_docente:
            aplicar_firma_a_slide(imagen_path, firma_docente, posicion_firma)
        print(f"    -> Guardada diapositiva {i+1}/{total_paginas}")
    return total_paginas

# ---------------------------------------------------------------------------
# Paso 2: Procesamiento del guion
# ---------------------------------------------------------------------------

def procesar_guion_texto(guion_path, total_paginas):
    """
    Lee un archivo de guion de texto estructurado y lo divide por diapositivas.
    Soporta: 'Diapositiva X', '[Diapositiva X]', 'Slide X', '[Slide X]' al inicio de linea.
    """
    print(f"[*] Leyendo archivo de guion: {guion_path}")
    if not os.path.exists(guion_path):
        print(f"[!] Error: No se encontro el archivo de guion en {guion_path}")
        sys.exit(1)
    with open(guion_path, "r", encoding="utf-8") as f:
        lineas = f.readlines()
    guion_por_slide = {}
    slide_actual = None
    texto_acumulado = []
    patron_slide = re.compile(r'^\s*\[?(?:Slide|Diapositiva)\s*(\d+)\]?\s*:?\s*(?:\"|")?', re.IGNORECASE)
    for linea in lineas:
        linea_stripped = linea.strip()
        match = patron_slide.match(linea_stripped)
        if match:
            if slide_actual is not None:
                texto_final = " ".join(texto_acumulado)
                guion_por_slide[slide_actual] = limpiar_texto_locucion(texto_final)
            num_slide = int(match.group(1))
            slide_actual = num_slide
            resto = linea_stripped[match.end():].strip()
            texto_acumulado = [resto] if resto else []
        else:
            if slide_actual is not None:
                texto_acumulado.append(linea_stripped)
    if slide_actual is not None:
        texto_final = " ".join(texto_acumulado)
        guion_por_slide[slide_actual] = limpiar_texto_locucion(texto_final)
    return guion_por_slide

def limpiar_texto_locucion(texto):
    """Limpia etiquetas administrativas y comillas del guion hablado."""
    texto = re.sub(
        r'^\s*(?:Guion\s+de\s+Locucion\s*\(Audio\)\s*:?\s*|Guion\s+de\s+locucion\s*:?\s*|Audio\s*:?\s*|Locucion\s*:?\s*)',
        '', texto, flags=re.IGNORECASE
    )
    texto = texto.strip()
    if (texto.startswith('"') and texto.endswith('"')) or \
       (texto.startswith('“') and texto.endswith('”')):
        texto = texto[1:-1].strip()
    return texto

# ---------------------------------------------------------------------------
# Paso 3: Validacion de coincidencia PDF <-> Guion
# ---------------------------------------------------------------------------

def validar_coincidencia(total_paginas, guion_por_slide):
    """
    Valida la coincidencia estricta entre el PDF y el guion.

    Retorna un dict con:
      total_slides         : paginas del PDF
      total_locuciones     : entradas del guion con texto no vacio
      slides_con_voz       : slides que tienen locucion asignada
      slides_sin_voz       : slides del PDF sin locucion (quedaran en silencio)
      locuciones_huerfanas : entradas del guion cuyo numero supera el total de paginas (TEXTO PERDIDO)
      es_valido            : True solo si no hay locuciones huerfanas
    """
    slides_pdf = set(range(1, total_paginas + 1))
    slides_con_texto = {n for n, t in guion_por_slide.items() if t.strip()}

    slides_con_voz       = sorted(slides_con_texto & slides_pdf)
    slides_sin_voz       = sorted(slides_pdf - slides_con_texto)
    locuciones_huerfanas = sorted(slides_con_texto - slides_pdf)

    return {
        "total_slides":          total_paginas,
        "total_locuciones":      len(slides_con_texto),
        "slides_con_voz":        slides_con_voz,
        "slides_sin_voz":        slides_sin_voz,
        "locuciones_huerfanas":  locuciones_huerfanas,
        "es_valido":             len(locuciones_huerfanas) == 0,
    }

def imprimir_reporte_validacion(reporte):
    """Imprime el reporte de validacion en consola con indicadores visuales."""
    print("\n" + "=" * 60)
    print("   VALIDACION DE COINCIDENCIA PDF <-> GUION")
    print("=" * 60)
    print(f"  [PDF]    Diapositivas detectadas : {reporte['total_slides']}")
    print(f"  [GUION]  Locuciones encontradas  : {reporte['total_locuciones']}")
    print(f"  [OK]     Slides con voz asignada : {len(reporte['slides_con_voz'])}  -> {reporte['slides_con_voz'] or 'ninguno'}")

    if reporte['slides_sin_voz']:
        print(f"  [AVISO]  Slides SIN locucion     : {len(reporte['slides_sin_voz'])}  -> {reporte['slides_sin_voz']}")
        print("           (Se mostraran en silencio por 2 segundos)")
    else:
        print("  [OK]     Todos los slides tienen locucion asignada")

    if reporte['locuciones_huerfanas']:
        print(f"  [ERROR]  Locuciones HUERFANAS    : {len(reporte['locuciones_huerfanas'])}  -> {reporte['locuciones_huerfanas']}")
        print("           ESTAS LOCUCIONES NO SE NARRARAN (numero de slide > total de paginas del PDF)")
    else:
        print("  [OK]     Sin locuciones huerfanas")

    print("=" * 60 + "\n")

# ---------------------------------------------------------------------------
# Paso 4: Optimizacion con Gemini
# ---------------------------------------------------------------------------

def optimizar_texto_con_gemini(texto, model_name):
    """Utiliza Gemini para corregir fonetica, abreviaturas y disonancias en el guion."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("[!] Advertencia: GEMINI_API_KEY no configurada. Saltando optimizacion fonetica.")
        return texto
    try:
        client = genai.Client()
        prompt = (
            "Eres un experto en locucion y redaccion academica. Tu tarea es optimizar el siguiente texto "
            "para que sea leido por un sistema de sintesis de voz (TTS) de forma fluida y natural.\n\n"
            "REGLAS:\n"
            "1. Expande abreviaturas, siglas medicas, simbolos o expresiones cientificas a su pronunciacion hablada en espanol.\n"
            "   Ejemplos: 'ABO/Rh' -> 'A B O y R H', 'pH' -> 'pe hache', 'mg/dl' -> 'miligramos por decilitro',\n"
            "   'vs.' -> 'versus', '/' -> 'y' o 'barra', '&' -> 'y', '1/2' -> 'un medio'.\n"
            "2. Mantene el tono academico e instructivo original.\n"
            "3. Devuelve UNICAMENTE el texto optimizado, sin comentarios ni preambulos.\n\n"
            f"Texto:\n{texto}"
        )
        response = client.models.generate_content(model=model_name, contents=prompt)
        return response.text.strip()
    except Exception as e:
        print(f"[!] Error al invocar Gemini: {e}. Se usara el texto original.")
        return texto

# ---------------------------------------------------------------------------
# Paso 5: Generacion de audio (silencio real + reintento en TTS)
# ---------------------------------------------------------------------------

def _generar_wav_silencio(output_path, duracion_s=2.0, sample_rate=24000):
    """
    Genera un archivo WAV de silencio puro (PCM 16-bit mono) sin llamar a edge-tts.
    Evita que slides sin locucion generen audio de puntos suspensivos.
    """
    num_samples = int(sample_rate * duracion_s)
    num_bytes   = num_samples * 2  # 16-bit = 2 bytes por muestra
    with open(output_path, "wb") as f:
        f.write(b"RIFF")
        f.write(struct.pack("<I", 36 + num_bytes))
        f.write(b"WAVE")
        f.write(b"fmt ")
        f.write(struct.pack("<I", 16))
        f.write(struct.pack("<H", 1))               # PCM
        f.write(struct.pack("<H", 1))               # mono
        f.write(struct.pack("<I", sample_rate))
        f.write(struct.pack("<I", sample_rate * 2))
        f.write(struct.pack("<H", 2))
        f.write(struct.pack("<H", 16))
        f.write(b"data")
        f.write(struct.pack("<I", num_bytes))
        f.write(b"\x00" * num_bytes)

async def _intentar_generar_audio(texto, voz, output_path, reintentos=3):
    """Llama a edge-tts con hasta `reintentos` intentos ante fallos de red o TTS."""
    for intento in range(1, reintentos + 1):
        try:
            communicate = edge_tts.Communicate(texto, voz)
            await communicate.save(output_path)
            return
        except Exception as e:
            if intento < reintentos:
                print(f"    [!] edge-tts fallo (intento {intento}/{reintentos}): {e}. Reintentando...")
                await asyncio.sleep(1.5 * intento)
            else:
                raise RuntimeError(
                    f"edge-tts no pudo generar audio tras {reintentos} intentos. Ultimo error: {e}"
                )

async def generar_todos_los_audios(guion_por_slide, voz, optimizar_ia, modelo_gemini, total_paginas):
    """
    Genera audio para cada slide del PDF (1..total_paginas):
    - Con texto: edge-tts con reintento automatico.
    - Sin texto: WAV de silencio puro (2 s), sin llamar a TTS.
    Si TTS falla definitivamente, usa silencio de 3 s como fallback en vez de abortar.
    """
    print("[*] Iniciando generacion de locuciones de voz neural...")
    errores = []

    for num_slide in range(1, total_paginas + 1):
        texto = guion_por_slide.get(num_slide, "").strip()

        if not texto:
            wav_silencio = os.path.join(TEMP_DIR, f"audio_{num_slide:03d}.wav")
            _generar_wav_silencio(wav_silencio)
            print(f"    -> Diapositiva {num_slide}: silencio generado (2 s)")
            continue

        texto_procesado = texto
        if optimizar_ia:
            print(f"    -> Optimizando texto de diapositiva {num_slide} con Gemini...")
            texto_procesado = optimizar_texto_con_gemini(texto, modelo_gemini)

        output_audio = os.path.join(TEMP_DIR, f"audio_{num_slide:03d}.mp3")
        try:
            await _intentar_generar_audio(texto_procesado, voz, output_audio)
            print(f"    -> Diapositiva {num_slide}: audio TTS generado")
        except RuntimeError as e:
            print(f"    [!] ERROR definitivo en diapositiva {num_slide}: {e}")
            wav_fallback = os.path.join(TEMP_DIR, f"audio_{num_slide:03d}.wav")
            _generar_wav_silencio(wav_fallback, duracion_s=3.0)
            errores.append(num_slide)
            print(f"    [!] Diapositiva {num_slide}: usando silencio de respaldo.")

    if errores:
        print(f"\n[!] ADVERTENCIA: {len(errores)} diapositiva(s) usaron silencio por fallo de TTS: {errores}")

# ---------------------------------------------------------------------------
# Paso 6: Ensamblado del video final
# ---------------------------------------------------------------------------

def ensamblar_video_final(total_slides, video_salida):
    """Une las imagenes con sus audios y genera el MP4 final."""
    print("[*] Iniciando ensamblado de video con MoviePy...")
    video_clips = []
    audio_clips = []

    for i in range(1, total_slides + 1):
        imagen_path    = os.path.join(TEMP_DIR, f"slide_{i:03d}.png")
        audio_path_mp3 = os.path.join(TEMP_DIR, f"audio_{i:03d}.mp3")
        audio_path_wav = os.path.join(TEMP_DIR, f"audio_{i:03d}.wav")
        audio_path     = audio_path_mp3 if os.path.exists(audio_path_mp3) else \
                         audio_path_wav  if os.path.exists(audio_path_wav) else None

        if not os.path.exists(imagen_path):
            print(f"[!] Error: Falta imagen de diapositiva {i}")
            continue

        if audio_path:
            print(f"    -> Procesando Diapositiva {i}/{total_slides} (con audio)")
            audio_clip = AudioFileClip(audio_path)
            video_clip = ImageClip(imagen_path).with_duration(audio_clip.duration)
            video_clips.append(video_clip)
            audio_clips.append(audio_clip)
        else:
            print(f"    -> Procesando Diapositiva {i}/{total_slides} (sin audio - 2 s)")
            video_clips.append(ImageClip(imagen_path).with_duration(2.0))

    print("[*] Concatenando diapositivas...")
    video_final = concatenate_videoclips(video_clips, method="chain")

    if audio_clips:
        print("[*] Concatenando pista de audio...")
        audio_final = concatenate_audioclips(audio_clips)
        video_final = video_final.with_audio(audio_final)

    print("[*] Renderizando MP4 final...")
    video_final.write_videofile(
        video_salida,
        fps=2,
        codec="libx264",
        preset="ultrafast",
        audio_codec="aac",
        temp_audiofile=os.path.join(TEMP_DIR, "temp_audio_final.m4a"),
        remove_temp=True
    )

    for clip in video_clips:
        clip.close()
    for clip in audio_clips:
        clip.close()
    if audio_clips:
        audio_final.close()
    video_final.close()

    print(f"[+] Video final generado correctamente en: {video_salida}")

# ---------------------------------------------------------------------------
# Funcion principal de orquestacion (usada por CLI y Streamlit)
# ---------------------------------------------------------------------------

def ejecutar_proceso_automatizacion(
    pdf_path, guion_path, video_salida, voz,
    optimizar_ia, modelo_gemini="gemini-2.5-flash",
    api_key=None, callback_progreso=None,
    firma_docente=None, posicion_firma="derecha"
):
    """
    Ejecuta el flujo completo de automatizacion de video.
    Retorna el reporte de validacion para que la UI lo pueda mostrar.
    """
    if api_key:
        os.environ["GEMINI_API_KEY"] = api_key

    limpiar_carpeta_temporal()

    if callback_progreso:
        callback_progreso("Extrayendo diapositivas del PDF...", 0.05)
    total_paginas = extraer_diapositivas_pdf(pdf_path, firma_docente, posicion_firma)

    if callback_progreso:
        callback_progreso("Procesando guion de voz...", 0.20)
    guion_por_slide = procesar_guion_texto(guion_path, total_paginas)

    reporte = validar_coincidencia(total_paginas, guion_por_slide)

    if callback_progreso:
        callback_progreso("Generando locuciones con voz neural...", 0.40)
    run_async(generar_todos_los_audios(
        guion_por_slide, voz, optimizar_ia, modelo_gemini, total_paginas
    ))

    if callback_progreso:
        callback_progreso("Sincronizando y renderizando video final...", 0.80)
    ensamblar_video_final(total_paginas, video_salida)

    if os.path.exists(TEMP_DIR):
        shutil.rmtree(TEMP_DIR)

    if callback_progreso:
        callback_progreso("Video finalizado con exito!", 1.0)

    return reporte

# ---------------------------------------------------------------------------
# Modo CLI
# ---------------------------------------------------------------------------

def main():
    """
    Ejecucion por linea de comandos.
    Requiere config.json en el mismo directorio.
    Para optimizacion con IA: export GEMINI_API_KEY='tu_clave'
    (Genera la clave en https://aistudio.google.com/app/apikey)
    """
    print("=" * 60)
    print("   AUTOMATIZADOR DE VIDEOS PARA CLASES ASINCRONICAS (MOODLE)")
    print("=" * 60)

    config = cargar_configuracion()
    pdf_entrada   = obtener_ruta_absoluta(config.get("pdf_entrada",    "diapositivas.pdf"))
    guion_entrada = obtener_ruta_absoluta(config.get("guion_entrada",  "guion.txt"))
    video_salida  = obtener_ruta_absoluta(config.get("video_salida",   "clase_final.mp4"))
    voz           = config.get("voz",                  "es-ES-AlvaroNeural")
    optimizar_ia  = config.get("optimizar_con_gemini", True)
    modelo_gemini = config.get("modelo_gemini",        "gemini-2.5-flash")
    firma_docente = config.get("firma_docente",        "")
    posicion_firma = config.get("posicion_firma",      "derecha")

    print(f"[*] PDF de entrada  : {pdf_entrada}")
    print(f"[*] Guion de entrada: {guion_entrada}")
    print(f"[*] Video de salida : {video_salida}")
    print(f"[*] Voz seleccionada: {voz}")
    print(f"[*] Optimizacion IA : {'SI' if optimizar_ia else 'NO'}")
    if firma_docente:
        print(f"[*] Firma Docente   : {firma_docente} ({posicion_firma})")
    if optimizar_ia and not os.environ.get("GEMINI_API_KEY"):
        print("\n[!] ADVERTENCIA: GEMINI_API_KEY no esta definida.")
        print("    Generala en: https://aistudio.google.com/app/apikey")
        print("    Luego ejecuta: export GEMINI_API_KEY='tu_clave_aqui'")
        print("    O desactiva la optimizacion en config.json con: \"optimizar_con_gemini\": false\n")
    print("-" * 60)

    limpiar_carpeta_temporal()
    total_paginas   = extraer_diapositivas_pdf(pdf_entrada, firma_docente, posicion_firma)
    guion_por_slide = procesar_guion_texto(guion_entrada, total_paginas)

    reporte = validar_coincidencia(total_paginas, guion_por_slide)
    imprimir_reporte_validacion(reporte)

    # Bloquear si hay locuciones huerfanas (siempre es un error de numeracion)
    if reporte["locuciones_huerfanas"]:
        print("[!] ERROR BLOQUEANTE: locuciones con numero de slide inexistente en el PDF.")
        print(f"    Slides invalidos: {reporte['locuciones_huerfanas']}")
        print("    Corrige la numeracion del guion y vuelve a intentarlo.")
        sys.exit(1)

    # Advertir y pedir confirmacion si hay slides sin locucion
    if reporte["slides_sin_voz"]:
        respuesta = input(
            f"[?] Los slides {reporte['slides_sin_voz']} quedaran en silencio. "
            "Continuar de todas formas? [s/N]: "
        ).strip().lower()
        if respuesta not in ("s", "si", "y", "yes"):
            print("[*] Proceso cancelado por el usuario.")
            sys.exit(0)

    run_async(generar_todos_los_audios(
        guion_por_slide, voz, optimizar_ia, modelo_gemini, total_paginas
    ))
    ensamblar_video_final(total_paginas, video_salida)

    if os.path.exists(TEMP_DIR):
        shutil.rmtree(TEMP_DIR)
        print("[*] Carpeta temporal limpiada.")

    print("=" * 60)
    print("   PROCESO TERMINADO CON EXITO")
    print("=" * 60)

if __name__ == "__main__":
    main()
