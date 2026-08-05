"""
app.py — точка входа FastAPI приложения.
Запуск: uvicorn app:app --reload
"""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from dotenv import load_dotenv

from execution.api.routers.health import router as health_router
from execution.api.routers.analyze import router as analyze_router
from execution.database.db import init_db
from execution.rag.rag_service import init_rag_db
from execution.api.routers.review import router as review_router
from execution.api.routers.telegram import router as telegram_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Инициализация при старте сервера"""
    load_dotenv()
    init_db()
    init_rag_db()
    yield
    # Cleanup при остановке (если нужно)


app = FastAPI(
    title="LexRadar API",
    description="AI-powered legal contract analysis",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(health_router)
app.include_router(analyze_router)
app.include_router(review_router)
app.include_router(telegram_router)