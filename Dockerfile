# Imagem do PILAS — bot do Telegram (polling).
FROM python:3.12-slim

WORKDIR /app

# Dependências
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Código
COPY . .

# Dados persistentes (banco + gráficos) vão pra um volume montado em /data.
ENV DB_PATH=/data/pilas.db \
    CHARTS_DIR=/data/charts \
    PYTHONUNBUFFERED=1

# Cria /data caso o host não monte um volume (modo sem persistência)
RUN mkdir -p /data

CMD ["python", "bot.py"]
