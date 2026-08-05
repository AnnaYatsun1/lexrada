"""
Notifier service — абстрактный интерфейс для отправки уведомлений через разные каналы.

Принцип: Separation of Concerns
- Генерация summary отдельно от доставки
- Каждый канал — отдельный класс
- Легко добавлять новые каналы (SMS, Slack, вебхук)
- Ошибки доставки не валят основной pipeline

Observability:
- Каждая попытка отправки логируется в БД (для метрик и отладки)
- Retry с exponential backoff встроен в каждый notifier
"""

from abc import ABC, abstractmethod
from typing import Optional
import os
import requests
import logging
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type, before_sleep_log
import time

logger = logging.getLogger(__name__)


class NotificationResult:
    """Результат попытки отправки"""
    def __init__(self, success: bool, channel: str, message: str, latency_ms: int = 0):
        self.success = success
        self.channel = channel
        self.message = message
        self.latency_ms = latency_ms

    def __repr__(self):
        status = "✅" if self.success else "❌"
        return f"{status} {self.channel}: {self.message} ({self.latency_ms}ms)"


class Notifier(ABC):
    """Абстрактный класс для отправки уведомлений"""
    
    @abstractmethod
    def send(self, text: str) -> NotificationResult:
        """Отправить уведомление через конкретный канал"""
        pass

    @abstractmethod
    def is_configured(self) -> bool:
        """Проверить, что канал правильно настроен (есть credentials)"""
        pass


class TelegramNotifier(Notifier):
    """Отправка в Telegram с retry и observability"""
    
    def __init__(self, token: Optional[str] = None, chat_id: Optional[str] = None):
        self.token = token or os.getenv("TELEGRAM_TOKEN")
        self.chat_id = chat_id or os.getenv("TELEGRAM_CHAT_ID")
    
    def is_configured(self) -> bool:
        return bool(self.token and self.chat_id)
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((
            requests.ConnectionError,
            requests.Timeout,
            requests.HTTPError,
        )),
        reraise=True,
        before_sleep=before_sleep_log(logger, logging.WARNING),
    )
    def _send_request(self, text: str) -> dict:
        """Внутренний метод с retry логикой"""
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        max_length = 4000
        if len(text) > max_length:
            parts = [text[i:i+max_length] for i in range(0, len(text), max_length)]
        else:
            parts = [text]
        result = None

        for part in parts:
            payload = {
                "chat_id": self.chat_id,
                "text": part
            }
            response = requests.post(url, json=payload, timeout=30)
            response.raise_for_status()
            return response.json()
        # else:
        #     payload = {
        #         "chat_id": self.chat_id,
        #         "text": text
        #     }
        # response = requests.post(url, json=payload, timeout=30)
        # response.raise_for_status()
        # return response.json()
    
    def send(self, text: str) -> NotificationResult:
        """Отправить сообщение в Telegram"""
        if not self.is_configured():
            msg = "Telegram is not configured: missing TELEGRAM_TOKEN or TELEGRAM_CHAT_ID"
            logger.warning(msg)
            return NotificationResult(
                success=False,
                channel="telegram",
                message=msg
            )
        
        try:
            start = time.time()
            self._send_request(text)
            latency_ms = int((time.time() - start) * 1000)
            
            logger.info(f"✅ Telegram: сообщение отправлено ({latency_ms}ms)")
            return NotificationResult(
                success=True,
                channel="telegram",
                message="Message sent successfully",
                latency_ms=latency_ms
            )
        except Exception as e:
            logger.exception(f"❌ Telegram: ошибка отправки: {e}")
            return NotificationResult(
                success=False,
                channel="telegram",
                message=f"Failed to send: {str(e)}"
            )


class EmailNotifier(Notifier):
    """Отправка по email (объявление на Неделе 1.5, реализация позже)
    
    На Неделе 2–3 интегрируем с:
    - SendGrid API (для production)
    - или Mailgun (бюджетный вариант)
    или локальный SMTP для dev
    """
    
    def __init__(self, smtp_host: Optional[str] = None, smtp_port: int = 587, 
                 email_from: Optional[str] = None, email_to: Optional[str] = None):
        self.smtp_host = smtp_host or os.getenv("SMTP_HOST")
        self.smtp_port = smtp_port
        self.email_from = email_from or os.getenv("EMAIL_FROM")
        self.email_to = email_to or os.getenv("EMAIL_TO")
    
    def is_configured(self) -> bool:
        # TODO: заменить на реальную проверку когда будет реализация
        return False
    
    def send(self, text: str) -> NotificationResult:
        """Отправить по email (TODO: реализация)"""
        msg = "EmailNotifier not yet implemented. Coming in Week 2–3."
        logger.warning(msg)
        return NotificationResult(
            success=False,
            channel="email",
            message=msg
        )


class NotifierManager:
    """Управляет несколькими notifiers, пробует отправить через все доступные каналы"""
    
    def __init__(self, notifiers: dict[str, Notifier]):
        """
        Args:
            notifiers: словарь {channel_name: Notifier_instance}
        """
        self.notifiers = notifiers
    
    def send_all(self, text: str, processing_id: Optional[int] = None) -> dict[str, NotificationResult]:
        """Отправить через все доступные каналы, собрать результаты"""
        results = {}
        
        for channel_name, notifier in self.notifiers.items():
            if not notifier.is_configured():
                logger.debug(f"⏭️  {channel_name}: not configured, skipping")
                continue
            
            result = notifier.send(text)
            results[channel_name] = result
            logger.info(f"📬 Delivery {channel_name}: {result}")
            
            # 📊 Логируем ВНУТРИ цикла для каждого канала
            if processing_id:
                from execution.database.db import record_delivery_attempt
                record_delivery_attempt(
                    processing_id=processing_id,
                    channel=channel_name,
                    success=result.success,
                    latency_ms=result.latency_ms,
                    error_message=None if result.success else result.message
                )
        
        if not results:
            logger.warning("⚠️  No notifiers are configured!")
        
        return results
    
    def send_primary(self, text: str, processing_id: Optional[int] = None, primary_channel: str = "telegram") -> NotificationResult:
        """Отправить через основной канал, fallback на другие при ошибке"""
        if primary_channel not in self.notifiers:
            raise ValueError(f"Unknown channel: {primary_channel}")
        
        from execution.database.db import record_delivery_attempt
        
        # Пробуем основной канал
        notifier = self.notifiers[primary_channel]
        if notifier.is_configured():
            result = notifier.send(text)
            
            # 📊 Логируем попытку основного канала
            if processing_id:
                record_delivery_attempt(
                    processing_id=processing_id,
                    channel=primary_channel,
                    success=result.success,
                    latency_ms=result.latency_ms,
                    error_message=None if result.success else result.message
                )
            
            if result.success:
                return result
            logger.warning(f"Primary channel {primary_channel} failed, trying fallbacks...")
        
        # Fallback на остальные
        for channel_name, notifier in self.notifiers.items():
            if channel_name == primary_channel:
                continue
            if notifier.is_configured():
                result = notifier.send(text)
                
                # 📊 Логируем fallback попытку
                if processing_id:
                    record_delivery_attempt(
                        processing_id=processing_id,
                        channel=channel_name,
                        success=result.success,
                        latency_ms=result.latency_ms,
                        error_message=None if result.success else result.message
                    )
                
                if result.success:
                    logger.info(f"✅ Fallback {channel_name} succeeded")
                    return result
        
        # Все каналы упали
        logger.error("❌ All notification channels failed")
        failed_result = NotificationResult(
            success=False,
            channel="all",
            message="All notification channels failed"
        )
        
        # 📊 Логируем полный провал
        if processing_id:
            record_delivery_attempt(
                processing_id=processing_id,
                channel="all",
                success=False,
                latency_ms=0,
                error_message="All channels failed"
            )
        
        return failed_result
    