from pydantic import BaseModel, Field


class RetrieveDocumentsInput(BaseModel):
    query: str = Field(..., description="Поисковый запрос для поиска похожих договоров")