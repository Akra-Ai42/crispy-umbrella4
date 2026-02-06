FROM python:3.11-slim

WORKDIR /app

# Installation des dépendances système nécessaires pour certaines libs Python (comme cffi/cryptography)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copie de l'ensemble du projet (app.py, rag.py et autres ressources potentielles)
COPY . .

# Lancement de l'application principale uniquement (rag.py est un module importé)
CMD ["python", "app.py"]