"""
Сервис расчёта стоимости LLM-вызовов.

На данный момент цены хранятся внутри сервиса (хардкод).
В будущем источник может быть заменён на LiteLLM / API / БД —
интерфейс сервиса не изменится.
"""


class PricingService:
    """Считает стоимость LLM-вызовов в USD."""

    # $ за 1M токенов
    _PRICING: dict[str, dict[str, float]] = {
        "claude-sonnet-4-5": {"input": 3.00, "output": 15.00},
        "claude-haiku-4-5": {"input": 0.80, "output": 4.00},
    }

    def calculate(self, model: str, tokens_in: int, tokens_out: int) -> float:
        prices = self._PRICING.get(model)
        if prices is None:
            return 0.0
        cost = (tokens_in * prices["input"] + tokens_out * prices["output"]) / 1_000_000
        return round(cost, 4)

    def estimate(
        self,
        model: str,
        expected_tokens_in: int,
        expected_tokens_out: int = 1000,
    ) -> float:
        """
        Предварительная оценка стоимости до вызова (для preview в UI).
        """
        return self.calculate(model, expected_tokens_in, expected_tokens_out)

    def supported_models(self) -> list[str]:
        """Список моделей для которых известна цена."""
        return list(self._PRICING.keys())