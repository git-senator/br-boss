FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt requirements-dev.txt ./
RUN pip install --upgrade pip && pip install -r requirements-dev.txt

COPY . .

# Não rodamos como root: se aparecer uma brecha na aplicação, ela não pode
# ter permissões de dono dentro do contêiner.
RUN useradd --create-home --uid 10001 boss && chown -R boss:boss /app
USER boss

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
