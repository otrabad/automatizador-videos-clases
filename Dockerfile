# Usar una imagen base oficial de Python
FROM python:3.9-slim

# Evitar la escritura de archivos .pyc en disco y asegurar salida de log inmediata
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Instalar FFmpeg y dependencias del sistema necesarias en la nube
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Establecer directorio de trabajo en el contenedor
WORKDIR /app

# Instalar dependencias de Python
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir \
    streamlit==1.50.0 \
    pymupdf==1.26.5 \
    edge-tts==7.2.8 \
    moviepy==2.2.1 \
    google-genai==1.47.0

# Copiar los archivos del script y de la interfaz al contenedor
COPY app.py /app/app.py
COPY automatizador.py /app/automatizador.py

# Exponer el puerto que Cloud Run utiliza por defecto (8080)
EXPOSE 8080

# Comando para ejecutar Streamlit escuchando en el puerto de Cloud Run
CMD ["streamlit", "run", "app.py", "--server.port=8080", "--server.address=0.0.0.0"]
