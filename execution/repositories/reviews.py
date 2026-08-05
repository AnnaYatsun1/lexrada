# execution/repositories/reviews.py

from datetime import datetime

from sqlalchemy.orm import Session

from execution.models.reviews import Review




class ReviewRepository:
    def __init__(self, session: Session):
        self.session = session

    def create(
        self,
        *,
        processing_id: int,
        reviewer_id: int,
        decision: str,
        comment: str | None,
        reviewed_at: datetime,
    ) -> Review:
        review = Review(
            processing_id=processing_id,
            reviewer_id=reviewer_id,
            decision=decision,
            comment=comment,
            reviewed_at=reviewed_at,
        )

        self.session.add(review)
        return review