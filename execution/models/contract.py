from pydantic import BaseModel, Field

class PartyOutput(BaseModel):
    """Структурированная информация о стороне договора"""
    name: str = Field(..., description="Наименование юрлица или ФИО")
    role: str | None = Field(None, description="Заказчик/Исполнитель/Покупатель/Продавец/Арендатор/Арендодатель/итд")
    inn: str | None = Field(None, description="ИНН (10 или 12 цифр)")
    ogrn: str | None = Field(None, description="ОГРН")
    kpp: str | None = Field(None, description="КПП")
    address: str | None = Field(None, description="Юридический адрес")
    signatory_name: str | None = Field(None, description="ФИО подписанта")
    signatory_position: str | None = Field(None, description="Должность подписанта")
    power_basis: str | None = Field(None, description="Основание полномочий (устав/доверенность)")
    power_number: str | None = Field(None, description="Номер доверенности если есть")
    power_date: str | None = Field(None, description="Дата доверенности")
    bank_account: str | None = Field(None, description="Банковский счёт для платежей")

class AgreementContractOutput(BaseModel):
    """Структурированный legal контракт"""
    document_number: str | None = Field(None, description="Номер договора")
    document_date: str | None = Field(None, description="Дата подписания (YYYY-MM-DD или текст)")
    
    parties: list[PartyOutput] = Field(default_factory=list, description="Стороны договора (2+)")
    
    subject: str | None = Field(None, description="Предмет договора (2-3 предложения)")
    price: str | None = Field(None, description="Сумма (с валютой и НДС если есть)")
    price_amount: float | None = Field(None, description="Сумма в числах")
    currency: str | None = Field(None, description="Валюта (RUB/USD/EUR)")
    
    payment_terms: str | None = Field(None, description="Порядок оплаты (авансе, постоплата, этапы)")
    delivery_terms: str | None = Field(None, description="Сроки/место доставки")
    execution_term: str | None = Field(None, description="Срок исполнения (дата или период)")
    
    penalties: str | None = Field(None, description="Штрафы/неустойки за нарушение")
    termination_terms: str | None = Field(None, description="Условия расторжения")
    liability: str | None = Field(None, description="Ответственность сторон (ограничена? неограниченна?)")
    
    acceptance_procedure: str | None = Field(None, description="Порядок приёмки/передачи")
    governing_law: str | None = Field(None, description="Применимое право (какой закон)")
    dispute_resolution: str | None = Field(None, description="Подсудность / арбитраж")
    
    additional_conditions: str | None = Field(None, description="Прочие существенные условия")