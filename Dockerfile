FROM python:3.13-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Прогреваем ChromaDB: скачиваем модель эмбеддингов заранее
RUN python -c "from chromadb.utils import embedding_functions; embedding_functions.ONNXMiniLM_L6_V2()._download_model_if_not_exists()"

COPY . .

EXPOSE 8000

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]