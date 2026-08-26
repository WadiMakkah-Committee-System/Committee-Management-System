"""
الهدف:
راوتات إدارة المسميات الوظيفية — وحدة مستقلة تمامًا عن الأدوار (Roles)،
تظهر كتبويب ثالث تحت "إدارة المستخدمين" (بعد "المستخدمون" و"الأدوار
والصلاحيات").
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser, require_permission
from app.db.session import get_db
from app.schemas.job_title import JobTitleCreate, JobTitleOut, JobTitleUpdate
from app.services import job_title_service

router = APIRouter(prefix="/job-titles", tags=["Job Titles"])


@router.get(
    "",
    response_model=list[JobTitleOut],
    dependencies=[Depends(require_permission("job_titles.view"))],
)
async def list_job_titles(db: AsyncSession = Depends(get_db)) -> list[JobTitleOut]:
    job_titles = await job_title_service.list_job_titles(db)
    return [JobTitleOut.model_validate(j) for j in job_titles]


@router.post(
    "",
    response_model=JobTitleOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("job_titles.create"))],
)
async def create_job_title(
    payload: JobTitleCreate, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
) -> JobTitleOut:
    try:
        job_title = await job_title_service.create_job_title(
            db, actor_user_id=current_user.user_id, name=payload.name
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return JobTitleOut.model_validate(job_title)


@router.patch(
    "/{job_title_id}",
    response_model=JobTitleOut,
    dependencies=[Depends(require_permission("job_titles.update"))],
)
async def update_job_title(
    job_title_id: uuid.UUID,
    payload: JobTitleUpdate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> JobTitleOut:
    try:
        job_title = await job_title_service.update_job_title(
            db, actor_user_id=current_user.user_id, job_title_id=job_title_id, name=payload.name
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if job_title is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="المسمى الوظيفي غير موجود")
    return JobTitleOut.model_validate(job_title)


@router.delete(
    "/{job_title_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission("job_titles.delete"))],
)
async def delete_job_title(
    job_title_id: uuid.UUID, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
) -> None:
    try:
        job_title = await job_title_service.delete_job_title(
            db, actor_user_id=current_user.user_id, job_title_id=job_title_id
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if job_title is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="المسمى الوظيفي غير موجود")
