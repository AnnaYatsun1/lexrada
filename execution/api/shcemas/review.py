# execution/api/schemas/review.py

from datetime import datetime

from pydantic import BaseModel, Field, field_validator



class ApproveReviewRequest(BaseModel):
    comment: str | None = Field(
        default=None,
        max_length=2_000,
    )

    @field_validator("comment")
    @classmethod
    def normalize_comment(cls, value: str | None) -> str | None:
        if value is None:
            return None

        value = value.strip()
        return value or None


class RejectReviewRequest(BaseModel):
    comment: str = Field(
        min_length=1,
        max_length=2_000,
    )

    @field_validator("comment")
    @classmethod
    def validate_comment(cls, value: str) -> str:
        value = value.strip()

        if not value:
            raise ValueError("Comment must not be blank")

        return value


class ReviewQueueItem(BaseModel):
    processing_id: int
    filename: str
    created_at: datetime


class ReviewQueueResponse(BaseModel):
    count: int
    items: list[ReviewQueueItem]


class ReviewDetailResponse(BaseModel):
    processing_id: int
    filename: str
    review_status: str
    report_md: str
    created_at: datetime


class ReviewDecisionResponse(BaseModel):
    processing_id: int
    review_status: str
    reviewed_at: datetime