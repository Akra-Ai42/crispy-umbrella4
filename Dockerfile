FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ➜ Important : on copie app.py ET rag.py
COPY app.py .
COPY rag.py .

CMD ["python", "app.py"]
