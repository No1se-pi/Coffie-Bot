"""Validated admin image upload and safe public image delivery."""

from __future__ import annotations

from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Request, Response, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.session import get_db_session
from app.models.enums import PermissionCode
from app.repositories.admin import AdminRepository
from app.schemas.admin import MediaUploadResponse, media_upload_response
from app.security.rbac import Actor, require_permissions
from app.services.admin import MAX_MEDIA_BYTES, AdminService, RequestMetadata

router = APIRouter(tags=["media"])

MediaActor = Annotated[
    Actor,
    Depends(require_permissions(PermissionCode.ADMIN_CONTENT_MANAGE)),
]
StaffMediaActor = Annotated[
    Actor,
    Depends(require_permissions(PermissionCode.OWN_TIP_PROFILE_MANAGE)),
]


@router.post(
    "/admin/media",
    response_model=MediaUploadResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_media(
    request: Request,
    actor: MediaActor,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    upload: Annotated[UploadFile, File()],
    kind: Annotated[str, Form(min_length=1, max_length=32, pattern=r"^[a-z][a-z0-9_-]*$")],
) -> MediaUploadResponse:
    try:
        content = await upload.read(MAX_MEDIA_BYTES + 1)
    finally:
        await upload.close()
    settings = cast(Settings, request.app.state.settings)
    result = await AdminService(repository=AdminRepository(session)).upload_media(
        actor=actor,
        content=content,
        original_filename=upload.filename,
        claimed_content_type=upload.content_type,
        kind=kind,
        media_root=settings.media_root,
        metadata=RequestMetadata(
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("User-Agent"),
        ),
    )
    return media_upload_response(result)


@router.post(
    "/staff/me/media",
    response_model=MediaUploadResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_staff_media(
    request: Request,
    actor: StaffMediaActor,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    upload: Annotated[UploadFile, File()],
    kind: Annotated[
        str,
        Form(pattern=r"^(staff_profile|tip_qr)$"),
    ],
) -> MediaUploadResponse:
    try:
        content = await upload.read(MAX_MEDIA_BYTES + 1)
    finally:
        await upload.close()
    settings = cast(Settings, request.app.state.settings)
    result = await AdminService(repository=AdminRepository(session)).upload_media(
        actor=actor,
        content=content,
        original_filename=upload.filename,
        claimed_content_type=upload.content_type,
        kind=kind,
        media_root=settings.media_root,
        metadata=RequestMetadata(
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("User-Agent"),
        ),
    )
    return media_upload_response(result)


@router.get("/media/{media_id}", response_class=FileResponse)
async def serve_media(
    media_id: UUID,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> Response:
    settings = cast(Settings, request.app.state.settings)
    download = await AdminService(repository=AdminRepository(session)).get_media_download(
        media_id=media_id,
        media_root=settings.media_root,
    )
    return FileResponse(
        path=download.path,
        media_type=download.media_type,
        filename=download.filename,
        content_disposition_type="inline",
        headers={
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "public, max-age=86400, immutable",
            "ETag": f'"{download.sha256}"',
        },
    )
