"""
Pydantic модели для Golden Dataset.
Golden = эталонные данные для проверки качества extraction.
"""
from pydantic import BaseModel, Field
from typing import Optional


class GoldenParty(BaseModel):
    """Эталонная сторона договора"""
    name: str
    role: Optional[str] = None
    inn: Optional[str] = None
    ogrn: Optional[str] = None
    address: Optional[str] = None
    signatory_name: Optional[str] = None
    signatory_position: Optional[str] = None
    power_basis: Optional[str] = None


class GoldenExpectedOutput(BaseModel):
    """Эталонный результат extraction — те же поля что AgreementContractOutput"""
    document_number: Optional[str] = None
    document_date: Optional[str] = None
    parties: list[GoldenParty] = Field(default_factory=list)
    subject: Optional[str] = None
    price: Optional[str] = None
    price_amount: Optional[float] = None
    currency: Optional[str] = None
    payment_terms: Optional[str] = None
    delivery_terms: Optional[str] = None
    execution_term: Optional[str] = None
    penalties: Optional[str] = None
    termination_terms: Optional[str] = None
    liability: Optional[str] = None
    acceptance_procedure: Optional[str] = None
    governing_law: Optional[str] = None
    dispute_resolution: Optional[str] = None


class GoldenContract(BaseModel):
    """Один эталонный контракт"""
    contract_id: str
    file: str
    exact_fields: list[str] = []
    normalized_fields: list[str] = []
    semantic_fields: list[str] = []
    expected_output: GoldenExpectedOutput


def load_golden(path: str) -> list[GoldenContract]:
    """Загружает golden dataset из JSON и валидирует через Pydantic"""
    import json
    from pathlib import Path

    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    contracts = []
    for item in raw:
        for contract_id, data in item.items():
            contracts.append(GoldenContract(
                contract_id=contract_id,
                file=data["file"],
                expected_output=GoldenExpectedOutput(**data["expected_output"]),
            ))
    return contracts