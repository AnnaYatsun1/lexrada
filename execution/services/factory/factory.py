"""Фабрика NotifierManager для конкретного юзера."""
import os

from execution.services.notifier import EmailNotifier, NotifierManager, TelegramNotifier



def build_notifier_for_user(user: dict) -> NotifierManager:
    """
    Создаёт NotifierManager с настроенными каналами под конкретного юзера.
    
    Token бота — глобальный (один на систему).
    Chat_id, email — индивидуальные (из user).
    """
    notifiers = {}
    
    # Telegram: глобальный токен + личный chat_id юзера
    if user.get("telegram_chat_id"):
        notifiers["telegram"] = TelegramNotifier(
            token=os.getenv("TELEGRAM_TOKEN"),
            chat_id=user["telegram_chat_id"],
        )
    
    # Email: личный email юзера (когда EmailNotifier будет реализован)
    if user.get("email"):
        notifiers["email"] = EmailNotifier(
            email_to=user["email"]
        )
    
    return NotifierManager(notifiers=notifiers)