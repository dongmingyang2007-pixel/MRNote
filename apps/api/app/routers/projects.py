from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import (
    get_current_user,
    get_current_workspace_id,
    get_db_session,
    require_csrf_protection,
    require_workspace_write_access,
)
from app.core.errors import ApiError
from app.models import PipelineConfig, Project, User
from app.schemas.project import PaginatedProjects, ProjectCreate, ProjectOut, ProjectUpdate
from app.services.audit import write_audit_log
from app.services.chat_modes import normalize_chat_mode
from app.services.memory_roots import ensure_project_assistant_root
from app.services.project_cleanup import ProjectDeletionError, delete_project_permanently
from app.services.pipeline_models import DEFAULT_PIPELINE_MODELS, PIPELINE_SLOT_ORDER


router = APIRouter(prefix="/api/v1/projects", tags=["projects"])


@router.get("", response_model=PaginatedProjects)
def list_projects(
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
) -> PaginatedProjects:
    _ = current_user
    query = db.query(Project).filter(Project.workspace_id == workspace_id, Project.deleted_at.is_(None))
    items = query.order_by(Project.created_at.desc()).all()
    return PaginatedProjects(
        items=[ProjectOut.model_validate(item, from_attributes=True) for item in items],
        total=len(items),
    )


@router.post("", response_model=ProjectOut)
def create_project(
    payload: ProjectCreate,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
    _write_guard: None = Depends(require_workspace_write_access),
    _: None = Depends(require_csrf_protection),
) -> ProjectOut:
    project = Project(
        workspace_id=workspace_id,
        name=payload.name,
        description=payload.description,
        default_chat_mode=normalize_chat_mode(payload.default_chat_mode),
    )
    db.add(project)
    db.flush()
    root_memory, _ = ensure_project_assistant_root(db, project, reparent_orphans=False)
    project.assistant_root_memory_id = root_memory.id

    db.add_all(
        [
            PipelineConfig(
                project_id=project.id,
                model_type=model_type,
                model_id=DEFAULT_PIPELINE_MODELS[model_type],
                config_json={},
            )
            for model_type in PIPELINE_SLOT_ORDER
        ]
    )
    write_audit_log(
        db,
        workspace_id=workspace_id,
        actor_user_id=current_user.id,
        action="project.create",
        target_type="project",
        target_id=project.id,
    )
    db.commit()
    db.refresh(project)
    return ProjectOut.model_validate(project, from_attributes=True)


@router.get("/{project_id}", response_model=ProjectOut)
def get_project(
    project_id: str,
    db: Session = Depends(get_db_session),
    workspace_id: str = Depends(get_current_workspace_id),
) -> ProjectOut:
    project = (
        db.query(Project)
        .filter(Project.id == project_id, Project.workspace_id == workspace_id, Project.deleted_at.is_(None))
        .first()
    )
    if not project:
        raise ApiError("not_found", "Project not found", status_code=404)
    return ProjectOut.model_validate(project, from_attributes=True)


@router.patch("/{project_id}", response_model=ProjectOut)
def update_project(
    project_id: str,
    payload: ProjectUpdate,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
    _write_guard: None = Depends(require_workspace_write_access),
    _: None = Depends(require_csrf_protection),
) -> ProjectOut:
    project = (
        db.query(Project)
        .filter(Project.id == project_id, Project.workspace_id == workspace_id, Project.deleted_at.is_(None))
        .first()
    )
    if not project:
        raise ApiError("not_found", "Project not found", status_code=404)

    if payload.name is not None:
        project.name = payload.name
    if payload.description is not None:
        project.description = payload.description
    if payload.default_chat_mode is not None:
        project.default_chat_mode = normalize_chat_mode(payload.default_chat_mode)
    project.updated_at = datetime.now(timezone.utc)
    ensure_project_assistant_root(db, project, reparent_orphans=False)

    write_audit_log(
        db,
        workspace_id=workspace_id,
        actor_user_id=current_user.id,
        action="project.update",
        target_type="project",
        target_id=project.id,
    )
    db.commit()
    db.refresh(project)
    return ProjectOut.model_validate(project, from_attributes=True)


@router.delete("/{project_id}")
def delete_project(
    project_id: str,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
    _write_guard: None = Depends(require_workspace_write_access),
    _: None = Depends(require_csrf_protection),
) -> dict:
    project = (
        db.query(Project)
        .filter(Project.id == project_id, Project.workspace_id == workspace_id, Project.deleted_at.is_(None))
        .first()
    )
    if not project:
        raise ApiError("not_found", "Project not found", status_code=404)

    write_audit_log(
        db,
        workspace_id=workspace_id,
        actor_user_id=current_user.id,
        action="project.delete",
        target_type="project",
        target_id=project.id,
    )
    try:
        delete_project_permanently(db, project=project)
        db.commit()
    except ProjectDeletionError as exc:
        db.rollback()
        raise ApiError(
            "storage_delete_failed",
            f"Project deletion failed while removing {len(exc.failed_object_keys)} stored objects",
            status_code=500,
        ) from exc
    return {"ok": True, "status": "deleted"}
