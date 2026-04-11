from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import (
    enforce_rate_limit,
    get_current_user,
    get_current_workspace_id,
    get_db_session,
    require_csrf_protection,
    require_workspace_write_access,
)
from app.core.errors import ApiError
from app.models import Artifact, Model, ModelAlias, ModelVersion, User
from app.routers.utils import (
    get_model_in_workspace,
    get_project_in_workspace_or_404,
    get_training_job_in_workspace,
    get_training_run_in_workspace,
)
from app.schemas.model import (
    AliasUpdateRequest,
    ArtifactUploadPresignRequest,
    ArtifactUploadPresignResponse,
    ModelCreate,
    ModelOut,
    ModelVersionCreate,
    ModelVersionOut,
    RollbackRequest,
)
from app.services.audit import write_audit_log
from app.services.runtime_state import runtime_state
from app.services.storage import (
    build_download_name_from_object_key,
    build_manual_model_artifact_object_key,
    build_upload_id,
    create_presigned_post,
    create_presigned_get,
    object_exists,
    put_object_bytes,
)
from app.services.upload_validation import buffer_upload_body, ensure_uploaded_object_matches
from app.tasks.worker_tasks import cleanup_pending_model_artifact_upload


router = APIRouter(prefix="/api/v1/models", tags=["models"])


def _artifact_upload_scope(artifact_upload_id: str) -> str:
    return f"model-artifact:{artifact_upload_id}"


def _artifact_upload_ttl_seconds(session: dict) -> int:
    expires_at = session.get("expires_at")
    if isinstance(expires_at, (int, float)):
        remaining = int(float(expires_at) - datetime.now(timezone.utc).timestamp())
        return max(1, remaining)
    return settings.upload_session_ttl_seconds


def _model_version_to_dict(db: Session, model_version: ModelVersion, workspace_id: str) -> dict:
    payload = ModelVersionOut.model_validate(model_version, from_attributes=True).model_dump(mode="json")
    payload["source"] = None
    payload["artifact_filename"] = build_download_name_from_object_key(model_version.artifact_object_key)
    payload["artifact_download_url"] = create_presigned_get(
        bucket_name=settings.s3_private_bucket,
        object_key=model_version.artifact_object_key,
        download_name=payload["artifact_filename"],
    )
    if not model_version.run_id:
        return payload

    run = get_training_run_in_workspace(db, run_id=model_version.run_id, workspace_id=workspace_id)
    if not run:
        return payload

    job = get_training_job_in_workspace(db, job_id=run.training_job_id, workspace_id=workspace_id)
    if not job:
        return payload

    payload["source"] = {
        "training_job_id": job.id,
        "dataset_version_id": job.dataset_version_id,
        "recipe": job.recipe,
        "params_json": job.params_json,
    }
    return payload


@router.get("")
def list_models(
    project_id: str,
    db: Session = Depends(get_db_session),
    workspace_id: str = Depends(get_current_workspace_id),
) -> dict:
    project = get_project_in_workspace_or_404(db, project_id, workspace_id)
    models = (
        db.query(Model)
        .filter(Model.project_id == project_id, Model.deleted_at.is_(None))
        .order_by(Model.created_at.desc())
        .all()
    )
    return {"items": [ModelOut.model_validate(model, from_attributes=True) for model in models]}


@router.post("")
def create_model(
    payload: ModelCreate,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
    _write_guard: None = Depends(require_workspace_write_access),
    _: None = Depends(require_csrf_protection),
) -> dict:
    project = get_project_in_workspace_or_404(db, payload.project_id, workspace_id)

    model = Model(project_id=payload.project_id, name=payload.name, task_type=payload.task_type)
    db.add(model)
    write_audit_log(
        db,
        workspace_id=workspace_id,
        actor_user_id=current_user.id,
        action="model.create",
        target_type="model",
        target_id=model.id,
    )
    db.commit()
    db.refresh(model)
    return {"model": ModelOut.model_validate(model, from_attributes=True)}


@router.get("/{model_id}")
def get_model(
    model_id: str,
    db: Session = Depends(get_db_session),
    workspace_id: str = Depends(get_current_workspace_id),
) -> dict:
    model = get_model_in_workspace(db, model_id=model_id, workspace_id=workspace_id)
    if not model:
        raise ApiError("not_found", "Model not found", status_code=404)

    aliases = db.query(ModelAlias).filter(ModelAlias.model_id == model.id).all()
    return {
        "model": ModelOut.model_validate(model, from_attributes=True),
        "aliases": [
            {"id": alias.id, "alias": alias.alias, "model_version_id": alias.model_version_id}
            for alias in aliases
        ],
    }


@router.get("/{model_id}/versions")
def list_model_versions(
    model_id: str,
    db: Session = Depends(get_db_session),
    workspace_id: str = Depends(get_current_workspace_id),
) -> dict:
    model = get_model_in_workspace(db, model_id=model_id, workspace_id=workspace_id)
    if not model:
        raise ApiError("not_found", "Model not found", status_code=404)

    versions = (
        db.query(ModelVersion)
        .filter(ModelVersion.model_id == model_id, ModelVersion.deleted_at.is_(None))
        .order_by(ModelVersion.version.desc())
        .all()
    )
    return {"items": [_model_version_to_dict(db, v, workspace_id) for v in versions]}


@router.post("/{model_id}/artifact-uploads/presign", response_model=ArtifactUploadPresignResponse)
def presign_model_artifact_upload(
    model_id: str,
    payload: ArtifactUploadPresignRequest,
    request: Request,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
    _write_guard: None = Depends(require_workspace_write_access),
    _: None = Depends(require_csrf_protection),
) -> ArtifactUploadPresignResponse:
    enforce_rate_limit(
        request,
        scope="model-artifact-presign",
        identifier=current_user.id,
        limit=settings.model_artifact_presign_rate_limit_max,
        window_seconds=settings.model_artifact_presign_rate_limit_window_seconds,
    )
    model = get_model_in_workspace(db, model_id=model_id, workspace_id=workspace_id)
    if not model:
        raise ApiError("not_found", "Model not found", status_code=404)
    project = get_project_in_workspace_or_404(db, model.project_id, workspace_id)

    max_bytes = settings.upload_max_mb * 1024 * 1024
    if payload.size_bytes > max_bytes:
        raise ApiError("payload_too_large", f"File exceeds {settings.upload_max_mb}MB limit", status_code=413)

    artifact_upload_id = build_upload_id()
    object_key = build_manual_model_artifact_object_key(
        workspace_id=workspace_id,
        project_id=project.id,
        model_id=model.id,
        artifact_upload_id=artifact_upload_id,
        filename=payload.filename,
    )
    headers: dict[str, str] = {}
    fields: dict[str, str] = {}
    upload_method = "PUT"
    if settings.should_use_proxy_uploads():
        put_url = f"{str(request.base_url).rstrip('/')}/api/v1/models/{model_id}/artifact-uploads/proxy/{artifact_upload_id}"
        headers = {"Content-Type": payload.media_type}
    else:
        put_url, fields, headers = create_presigned_post(
            bucket_name=settings.s3_private_bucket,
            object_key=object_key,
            media_type=payload.media_type,
            max_bytes=payload.size_bytes,
        )
        upload_method = "POST"

    now = datetime.now(timezone.utc)
    runtime_state.set_json(
        _artifact_upload_scope(artifact_upload_id),
        "session",
        {
            "artifact_upload_id": artifact_upload_id,
            "model_id": model.id,
            "project_id": project.id,
            "workspace_id": workspace_id,
            "user_id": current_user.id,
            "object_key": object_key,
            "filename": payload.filename,
            "media_type": payload.media_type,
            "size_bytes": payload.size_bytes,
            "uploaded": False,
            "expires_at": now.timestamp() + settings.upload_session_ttl_seconds,
        },
        ttl_seconds=settings.upload_session_ttl_seconds,
    )
    try:
        cleanup_pending_model_artifact_upload.apply_async(
            args=[artifact_upload_id, object_key],
            countdown=settings.upload_session_ttl_seconds,
        )
    except Exception:  # noqa: BLE001
        pass
    return ArtifactUploadPresignResponse(
        artifact_upload_id=artifact_upload_id,
        put_url=put_url,
        headers=headers,
        fields=fields,
        upload_method=upload_method,
    )


@router.put("/{model_id}/artifact-uploads/proxy/{artifact_upload_id}")
async def proxy_model_artifact_upload(
    model_id: str,
    artifact_upload_id: str,
    request: Request,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
    _write_guard: None = Depends(require_workspace_write_access),
    _: None = Depends(require_csrf_protection),
) -> dict[str, bool]:
    model = get_model_in_workspace(db, model_id=model_id, workspace_id=workspace_id)
    if not model:
        raise ApiError("not_found", "Model not found", status_code=404)
    session = runtime_state.get_json(_artifact_upload_scope(artifact_upload_id), "session")
    if not session:
        raise ApiError("upload_not_found", "Artifact upload session not found", status_code=404)
    if session["model_id"] != model.id or session["user_id"] != current_user.id or session["workspace_id"] != workspace_id:
        raise ApiError("forbidden", "Artifact upload session not accessible", status_code=403)
    content_type = request.headers.get("content-type", "")
    if content_type and content_type != session["media_type"]:
        raise ApiError("content_type_mismatch", "Content-Type does not match upload session", status_code=400)

    buffered_upload = await buffer_upload_body(
        request,
        expected_size=session["size_bytes"],
        max_bytes=settings.upload_max_mb * 1024 * 1024,
    )
    try:
        if settings.env != "test":
            try:
                put_object_bytes(
                    bucket_name=settings.s3_private_bucket,
                    object_key=session["object_key"],
                    payload=buffered_upload.file,
                    media_type=session["media_type"],
                )
            except Exception as exc:  # noqa: BLE001
                raise ApiError("storage_error", "Object upload failed", status_code=502) from exc
    finally:
        buffered_upload.close()

    session["uploaded"] = True
    runtime_state.set_json(
        _artifact_upload_scope(artifact_upload_id),
        "session",
        session,
        ttl_seconds=_artifact_upload_ttl_seconds(session),
    )
    return {"ok": True}


@router.post("/{model_id}/versions")
def create_model_version(
    model_id: str,
    payload: ModelVersionCreate,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
    _write_guard: None = Depends(require_workspace_write_access),
    _: None = Depends(require_csrf_protection),
) -> dict:
    model = get_model_in_workspace(db, model_id=model_id, workspace_id=workspace_id)
    if not model:
        raise ApiError("not_found", "Model not found", status_code=404)
    project = get_project_in_workspace_or_404(db, model.project_id, workspace_id)
    if payload.run_id and payload.artifact_upload_id:
        raise ApiError("invalid_request", "Provide either run_id or artifact_upload_id, not both", status_code=400)

    artifact_object_key: str | None = None
    if payload.run_id:
        run = get_training_run_in_workspace(db, run_id=payload.run_id, workspace_id=workspace_id)
        if not run:
            raise ApiError("not_found", "Run not found", status_code=404)
        job = get_training_job_in_workspace(db, job_id=run.training_job_id, workspace_id=workspace_id)
        if not job:
            raise ApiError("not_found", "Training job not found for run", status_code=404)
        if job.project_id != model.project_id:
            raise ApiError("mismatch", "Run does not belong to this model's project", status_code=400)
        artifact = (
            db.query(Artifact)
            .filter(Artifact.run_id == run.id)
            .order_by(Artifact.created_at.desc())
            .first()
        )
        if not artifact:
            raise ApiError("artifact_not_found", "No managed artifact found for the selected run", status_code=400)
        artifact_object_key = artifact.object_key
    elif payload.artifact_upload_id:
        upload = runtime_state.get_json(_artifact_upload_scope(payload.artifact_upload_id), "session")
        if not upload:
            raise ApiError("upload_not_found", "Artifact upload session not found", status_code=404)
        if upload["model_id"] != model.id or upload["user_id"] != current_user.id or upload["workspace_id"] != workspace_id:
            raise ApiError("forbidden", "Artifact upload session not accessible", status_code=403)
        if not upload.get("uploaded"):
            if not object_exists(
                bucket_name=settings.s3_private_bucket,
                object_key=upload["object_key"],
            ):
                raise ApiError("upload_incomplete", "Managed artifact upload is incomplete", status_code=400)
            ensure_uploaded_object_matches(
                bucket_name=settings.s3_private_bucket,
                object_key=upload["object_key"],
                expected_size_bytes=upload["size_bytes"],
                expected_media_type=upload["media_type"],
                missing_message="Managed artifact upload is incomplete",
                mismatch_message="Managed artifact metadata does not match declared file",
            )
        artifact_object_key = upload["object_key"]
        runtime_state.delete(_artifact_upload_scope(payload.artifact_upload_id), "session")
    else:
        raise ApiError("artifact_required", "A managed run or artifact upload is required", status_code=400)

    max_version = db.query(func.max(ModelVersion.version)).filter(ModelVersion.model_id == model_id).scalar() or 0
    model_version = ModelVersion(
        model_id=model_id,
        version=max_version + 1,
        run_id=payload.run_id,
        metrics_json=payload.metrics_json,
        artifact_object_key=artifact_object_key,
        notes=payload.notes,
    )
    db.add(model_version)
    write_audit_log(
        db,
        workspace_id=workspace_id,
        actor_user_id=current_user.id,
        action="model_version.create",
        target_type="model_version",
        target_id=model_version.id,
        meta_json={"model_id": model_id, "version": model_version.version},
    )
    db.commit()
    db.refresh(model_version)
    return {"model_version": _model_version_to_dict(db, model_version, workspace_id)}


@router.post("/{model_id}/aliases")
def update_alias(
    model_id: str,
    payload: AliasUpdateRequest,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
    _write_guard: None = Depends(require_workspace_write_access),
    _: None = Depends(require_csrf_protection),
) -> dict:
    model = get_model_in_workspace(db, model_id=model_id, workspace_id=workspace_id)
    if not model:
        raise ApiError("not_found", "Model not found", status_code=404)

    version = (
        db.query(ModelVersion)
        .filter(
            ModelVersion.id == payload.model_version_id,
            ModelVersion.model_id == model_id,
            ModelVersion.deleted_at.is_(None),
        )
        .first()
    )
    if not version:
        raise ApiError("not_found", "Model version not found", status_code=404)

    alias = (
        db.query(ModelAlias)
        .filter(ModelAlias.model_id == model_id, ModelAlias.alias == payload.alias)
        .first()
    )
    if not alias:
        alias = ModelAlias(
            model_id=model_id,
            alias=payload.alias,
            model_version_id=payload.model_version_id,
            updated_at=datetime.now(timezone.utc),
        )
        db.add(alias)
        db.flush()
    else:
        alias.model_version_id = payload.model_version_id
        alias.updated_at = datetime.now(timezone.utc)

    write_audit_log(
        db,
        workspace_id=workspace_id,
        actor_user_id=current_user.id,
        action="model_alias.updated",
        target_type="model_alias",
        target_id=alias.id,
        meta_json={"alias": payload.alias, "model_version_id": payload.model_version_id},
    )
    db.commit()
    db.refresh(alias)
    return {"ok": True, "alias": {"alias": alias.alias, "model_version_id": alias.model_version_id}}


@router.post("/{model_id}/rollback")
def rollback_alias(
    model_id: str,
    payload: RollbackRequest,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
    _write_guard: None = Depends(require_workspace_write_access),
    _: None = Depends(require_csrf_protection),
) -> dict:
    model = get_model_in_workspace(db, model_id=model_id, workspace_id=workspace_id)
    if not model:
        raise ApiError("not_found", "Model not found", status_code=404)

    alias = (
        db.query(ModelAlias)
        .filter(ModelAlias.model_id == model_id, ModelAlias.alias == payload.alias)
        .first()
    )
    if not alias:
        raise ApiError("not_found", "Alias not found", status_code=404)

    version = (
        db.query(ModelVersion)
        .filter(
            ModelVersion.id == payload.to_model_version_id,
            ModelVersion.model_id == model_id,
            ModelVersion.deleted_at.is_(None),
        )
        .first()
    )
    if not version:
        raise ApiError("not_found", "Target model version not found", status_code=404)

    alias.model_version_id = payload.to_model_version_id
    alias.updated_at = datetime.now(timezone.utc)

    write_audit_log(
        db,
        workspace_id=workspace_id,
        actor_user_id=current_user.id,
        action="model_alias.rollback",
        target_type="model_alias",
        target_id=alias.id,
        meta_json={"alias": payload.alias, "to_model_version_id": payload.to_model_version_id},
    )
    db.commit()
    return {"ok": True}
