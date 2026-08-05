# execution/services/review.py

from datetime import UTC, datetime

from sqlalchemy.orm import Session


from execution.api.shcemas.review import ReviewDecisionResponse, ReviewDetailResponse, ReviewQueueResponse
from execution.repositories.processings import ProcessingRepository
# from execution.models.reviews import Review
from execution.repositories.reviews import ReviewRepository
from execution.services.storage import StorageService
from execution.api.shcemas.review import ReviewQueueItem, ReviewQueueResponse


class ReviewNotFoundError(Exception):
    pass


class ReviewConflictError(Exception):
    pass


class ReviewService:
    def __init__(
        self,
        session: Session,
        processing_repo: ProcessingRepository,
        review_repo: ReviewRepository,
        report_storage: StorageService,
    ):
        self._session = session
        self._processing_repo = processing_repo
        self._review_repo = review_repo
        self._report_storage = report_storage

    def get_pending_queue(
        self,
        reviewer_id: int,
    ) -> ReviewQueueResponse:
        reviews = self._review_repo.list_pending_for_reviewer(
            reviewer_id=reviewer_id,
        )

        items = [
            ReviewQueueItem(
                processing_id=review.processing.id,
                filename=review.processing.original_filename,
                created_at=review.created_at,
            )
            for review in reviews
        ]

        return ReviewQueueResponse(
            count=len(items),
            items=items,
        )

    def get_detail(
        self,
        processing_id: int,
        reviewer_id: int,
    ) -> ReviewDetailResponse:
        review = self._review_repo.get_for_reviewer(
            processing_id=processing_id,
            reviewer_id=reviewer_id,
        )

        if review is None:
            raise ReviewNotFoundError

        report_md = self._report_storage.read(
            review.processing.result_path,
        )

        return ReviewDetailResponse(
            processing_id=review.processing_id,
            filename=review.processing.original_filename,
            review_status=review.status,
            report_md=report_md,
            created_at=review.created_at,
        )

    def approve(
        self,
        processing_id: int,
        reviewer_id: int,
        comment: str | None,
    ) -> ReviewDecisionResponse:
        return self._make_decision(
            processing_id=processing_id,
            reviewer_id=reviewer_id,
            decision="approved",
            comment=comment,
        )

    def reject(
        self,
        processing_id: int,
        reviewer_id: int,
        comment: str,
    ) -> ReviewDecisionResponse:
        return self._make_decision(
            processing_id=processing_id,
            reviewer_id=reviewer_id,
            decision="rejected",
            comment=comment,
        )

    def _make_decision(
        self,
        processing_id: int,
        reviewer_id: int,
        decision: str,
        comment: str | None,
    ) -> ReviewDecisionResponse:
        try:
            review = self._review_repo.get_pending_for_update(
                processing_id=processing_id,
                reviewer_id=reviewer_id,
            )

            if review is None:
                existing = self._review_repo.get_for_reviewer(
                    processing_id=processing_id,
                    reviewer_id=reviewer_id,
                )

                if existing is None:
                    raise ReviewNotFoundError

                raise ReviewConflictError(
                    f"Review already has status '{existing.status}'"
                )

            reviewed_at = datetime.now(UTC)

            review.status = decision
            review.reviewer_id = reviewer_id
            review.comment = comment
            review.reviewed_at = reviewed_at

            self._session.commit()

            return ReviewDecisionResponse(
                processing_id=processing_id,
                review_status=decision,
                reviewed_at=reviewed_at,
            )

        except Exception:
            self._session.rollback()
            raise