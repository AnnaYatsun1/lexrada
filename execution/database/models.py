

from sqlalchemy.orm import DeclarativeBase

from datetime import datetime

from sqlalchemy import DateTime, Integer, LargeBinary, String, ForeignKey, Float
from sqlalchemy.orm import Mapped, mapped_column


class Base(DeclarativeBase):
    pass

class Processing(Base):
    __tablename__ = "processings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    file_hash: Mapped[str] = mapped_column(String, nullable=False)

    original_filename: Mapped[str] = mapped_column(String, nullable=False)
    file_content: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    celery_task_id: Mapped[str | None] = mapped_column(String, nullable=True)

    status: Mapped[str] = mapped_column(
        String,
        default="pending",
        nullable=False,
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
    )

    completed_at: Mapped[datetime | None] = mapped_column(DateTime)

    result_path: Mapped[str | None]

    error_message: Mapped[str | None]

    delivery_channel: Mapped[str | None]

    delivery_status: Mapped[str | None]

    delivery_attempt_count: Mapped[int] = mapped_column(
        default=0,
        nullable=False,
    )

    delivery_error: Mapped[str | None]

    delivered_at: Mapped[datetime | None]


class LLMCall(Base):
    __tablename__ = "llm_calls"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    processing_id: Mapped[int] = mapped_column(
        ForeignKey("processings.id"),
        nullable=False,
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)

    model: Mapped[str]

    stage: Mapped[str]

    tokens_in: Mapped[int]

    tokens_out: Mapped[int]

    latency_ms: Mapped[int]

    cost_usd: Mapped[float] = mapped_column(Float)

    status: Mapped[str] = mapped_column(
        default="success",
        nullable=False,
    )

    created_at: Mapped[datetime]

class Counterparty(Base):
    __tablename__ = "counterparties"
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), 
        primary_key=True,
        nullable=False)
    inn: Mapped[str] = mapped_column(
        String,
        primary_key=True,
    )

    name: Mapped[str]

    times_seen: Mapped[int] = mapped_column(
        Integer,
        default=1,
        nullable=False,
    )

    first_seen: Mapped[datetime]

    last_seen: Mapped[datetime]


class CounterpartyRisk(Base):
    __tablename__ = "counterparty_risks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    counterparty_inn: Mapped[str] = mapped_column(
    String,
    nullable=False,
)

    processing_id: Mapped[int] = mapped_column(
        ForeignKey("processings.id"),
        nullable=False,
    )

    document_number: Mapped[str | None]

    risk_text: Mapped[str]

    severity: Mapped[str] = mapped_column(
        default="MEDIUM",
        nullable=False,
    )

    found_at: Mapped[datetime]

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    email: Mapped[str | None] = mapped_column(
        String,
        unique=True,
    )

    api_key: Mapped[str] = mapped_column(
        String,
        unique=True,
        nullable=False,
    )

    name: Mapped[str | None]

    telegram_chat_id: Mapped[str | None]

    telegram_username: Mapped[str | None]

    preferred_delivery: Mapped[str] = mapped_column(
        default="telegram",
        nullable=False,
    )

    created_at: Mapped[datetime]

"""ORM-модель результата human review."""

from datetime import datetime

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column




# class Review(Base):
#     __tablename__ = "reviews"

#     id: Mapped[int] = mapped_column(
#         primary_key=True,
#         autoincrement=True,
#     )

#     processing_id: Mapped[int] = mapped_column(
#         ForeignKey("processings.id"),
#         nullable=False,
#         index=True,
#     )

#     reviewer_id: Mapped[int] = mapped_column(
#         ForeignKey("users.id"),
#         nullable=False,
#         index=True,
#     )

#     decision: Mapped[str] = mapped_column(
#         String(20),
#         nullable=False,
#     )

#     comment: Mapped[str | None] = mapped_column(
#         Text,
#         nullable=True,
#     )

#     reviewed_at: Mapped[datetime] = mapped_column(
#         nullable=False,
#     )