# execution/api/routers/review.py

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from execution.database.models import User
from execution.api.dependencies import (
    get_current_user,
    get_review_service,
)
from execution.api.shcemas.review import (
    ApproveReviewRequest,
    RejectReviewRequest,
    ReviewDecisionResponse,
    ReviewDetailResponse,
    ReviewQueueResponse,
)

from execution.api.shcemas.review import ApproveReviewRequest, RejectReviewRequest, ReviewDecisionResponse, ReviewDetailResponse, ReviewQueueResponse
from execution.services.review import (
    ReviewConflictError,
    ReviewNotFoundError,
    ReviewService,
)

router = APIRouter(prefix="/reviews", tags=["reviews"])

CurrentUser = Annotated[User, Depends(get_current_user)]
ReviewServiceDependency = Annotated[
    ReviewService,
    Depends(get_review_service),
]


@router.get(
    "/queue",
    response_model=ReviewQueueResponse,
)
def get_review_queue(
    current_user: CurrentUser,
    service: ReviewServiceDependency,
) -> ReviewQueueResponse:
    return service.get_pending_queue(
        reviewer_id=current_user.id,
    )


@router.get(
    "/{processing_id}",
    response_model=ReviewDetailResponse,
)
def get_review_detail(
    processing_id: int,
    current_user: CurrentUser,
    service: ReviewServiceDependency,
) -> ReviewDetailResponse:
    try:
        return service.get_detail(
            processing_id=processing_id,
            reviewer_id=current_user.id,
        )
    except ReviewNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Review not found",
        ) from exc


@router.post(
    "/{processing_id}/approve",
    response_model=ReviewDecisionResponse,
)
def approve_review(
    processing_id: int,
    body: ApproveReviewRequest,
    current_user: CurrentUser,
    service: ReviewServiceDependency,
) -> ReviewDecisionResponse:
    try:
        return service.approve(
            processing_id=processing_id,
            reviewer_id=current_user.id,
            comment=body.comment,
        )
    except ReviewNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Review not found",
        ) from exc
    except ReviewConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc


@router.post(
    "/{processing_id}/reject",
    response_model=ReviewDecisionResponse,
)
def reject_review(
    processing_id: int,
    body: RejectReviewRequest,
    current_user: CurrentUser,
    service: ReviewServiceDependency,
) -> ReviewDecisionResponse:
    try:
        return service.reject(
            processing_id=processing_id,
            reviewer_id=current_user.id,
            comment=body.comment,
        )
    except ReviewNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Review not found",
        ) from exc
    except ReviewConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc