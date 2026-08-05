"""
Инициализация Langfuse SDK.

Langfuse читает ключи из env-переменных:
- LANGFUSE_PUBLIC_KEY
- LANGFUSE_SECRET_KEY
- LANGFUSE_HOST

Импортируется один раз при старте приложения — обычно в главном модуле
(main.py для CLI или app.py для FastAPI).
"""
from langfuse import get_client

# Клиент инициализируется автоматически из env-переменных
langfuse = get_client()