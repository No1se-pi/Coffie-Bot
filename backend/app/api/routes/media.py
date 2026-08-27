"""Validated admin image upload and safe public image delivery."""

from __future__ import annotations

from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Request, Response, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError
from app.db.session import get_db_session
from app.models.enums import PermissionCode
from app.repositories.admin import AdminRepository
from app.schemas.admin import MediaUploadResponse, media_upload_response
from app.security.rbac import Actor, require_permissions
from app.services.admin import MAX_MEDIA_BYTES, AdminService, MediaDownload, RequestMetadata

router = APIRouter(tags=["media"])

MediaActor = Annotated[
    Actor,
    Depends(require_permissions(PermissionCode.ADMIN_CONTENT_MANAGE)),
]
StaffMediaActor = Annotated[
    Actor,
    Depends(require_permissions(PermissionCode.OWN_TIP_PROFILE_MANAGE)),
]
ReceiptMediaActor = Annotated[
    Actor,
    Depends(require_permissions(PermissionCode.RECEIPTS_MANAGE)),
]
ReceiptMediaReader = Annotated[
    Actor,
    Depends(require_permissions(PermissionCode.RECEIPTS_READ)),
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


@router.post(
    "/staff/receipts/media",
    response_model=MediaUploadResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_receipt_media(
    request: Request,
    actor: ReceiptMediaActor,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    upload: Annotated[UploadFile, File()],
) -> MediaUploadResponse:
    """Reuse signature/MIME/size validation with a receipt-specific media kind."""

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
        kind="receipt",
        media_root=settings.media_root,
        metadata=RequestMetadata(
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("User-Agent"),
        ),
    )
    response = media_upload_response(result)
    response.url = f"/api/v1/staff/receipts/media/{result.media.id}"
    return response


@router.get("/staff/receipts/media/{media_id}", response_class=FileResponse)
async def serve_receipt_media(
    media_id: UUID,
    request: Request,
    _actor: ReceiptMediaReader,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> Response:
    """Receipt photos are staff-private even when their opaque UUID leaks."""

    settings = cast(Settings, request.app.state.settings)
    download = await AdminService(repository=AdminRepository(session)).get_media_download(
        media_id=media_id,
        media_root=settings.media_root,
    )
    if download.kind != "receipt":
        raise AppError(code="not_found", message="Media file was not found", status_code=404)
    return _file_response(download)


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
    if download.kind == "receipt":
        # Do not reveal whether a private receipt image exists.
        raise AppError(code="not_found", message="Media file was not found", status_code=404)
    return _file_response(download)


def _file_response(download: MediaDownload) -> Response:
    """Build identical safe headers for public and authorized private images."""

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
