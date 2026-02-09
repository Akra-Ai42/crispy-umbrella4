FROM python:3.11-slim

WORKDIR /app

# AJOUT CRITIQUE : Installation de tous les outils de compilation nécessaires
# gcc, g++, make, libffi-dev, libssl-dev sont indispensables pour chromadb/cffi
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    g++ \
    make \
    libffi-dev \
    libssl-dev \
    && rm -rf /var/lib/apt/lists/*

# Copie des requirements
COPY requirements.txt .

# Mise à jour de pip (important) et installation des dépendances
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copie du reste du code
COPY . .

# Lancement
CMD ["python", "app.py"]