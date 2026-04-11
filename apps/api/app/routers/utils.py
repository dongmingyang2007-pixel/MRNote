from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.models import DataItem, Dataset, Membership, Model, Project, TrainingJob, TrainingRun


def user_has_workspace_access(db: Session, user_id: str, workspace_id: str) -> bool:
    return (
        db.query(Membership)
        .filter(Membership.user_id == user_id, Membership.workspace_id == workspace_id)
        .first()
        is not None
    )


def get_project_in_workspace(
    db: Session,
    *,
    project_id: str,
    workspace_id: str,
    include_deleted: bool = False,
) -> Project | None:
    query = db.query(Project).filter(Project.id == project_id, Project.workspace_id == workspace_id)
    if not include_deleted:
        query = query.filter(Project.deleted_at.is_(None))
    return query.first()


def get_project_in_workspace_or_404(
    db: Session,
    project_id: str,
    workspace_id: str,
) -> Project:
    """Get project or raise ApiError(404)."""
    project = get_project_in_workspace(db, project_id=project_id, workspace_id=workspace_id)
    if not project:
        raise ApiError("not_found", "Project not found", status_code=404)
    return project


def get_dataset_in_workspace(
    db: Session,
    *,
    dataset_id: str,
    workspace_id: str,
    include_deleted: bool = False,
) -> Dataset | None:
    query = (
        db.query(Dataset)
        .join(Project, Dataset.project_id == Project.id)
        .filter(Dataset.id == dataset_id, Project.workspace_id == workspace_id)
    )
    if not include_deleted:
        query = query.filter(Dataset.deleted_at.is_(None), Project.deleted_at.is_(None))
    return query.first()


def get_data_item_in_workspace(
    db: Session,
    *,
    data_item_id: str,
    workspace_id: str,
    include_deleted: bool = False,
) -> DataItem | None:
    query = (
        db.query(DataItem)
        .join(Dataset, Dataset.id == DataItem.dataset_id)
        .join(Project, Project.id == Dataset.project_id)
        .filter(DataItem.id == data_item_id, Project.workspace_id == workspace_id)
    )
    if not include_deleted:
        query = query.filter(
            DataItem.deleted_at.is_(None),
            Dataset.deleted_at.is_(None),
            Project.deleted_at.is_(None),
        )
    return query.first()


def get_training_job_in_workspace(
    db: Session,
    *,
    job_id: str,
    workspace_id: str,
) -> TrainingJob | None:
    return (
        db.query(TrainingJob)
        .join(Project, Project.id == TrainingJob.project_id)
        .filter(
            TrainingJob.id == job_id,
            Project.deleted_at.is_(None),
            Project.workspace_id == workspace_id,
        )
        .first()
    )


def get_training_run_in_workspace(
    db: Session,
    *,
    run_id: str,
    workspace_id: str,
) -> TrainingRun | None:
    return (
        db.query(TrainingRun)
        .join(TrainingJob, TrainingJob.id == TrainingRun.training_job_id)
        .join(Project, Project.id == TrainingJob.project_id)
        .filter(
            TrainingRun.id == run_id,
            Project.deleted_at.is_(None),
            Project.workspace_id == workspace_id,
        )
        .first()
    )


def get_model_in_workspace(
    db: Session,
    *,
    model_id: str,
    workspace_id: str,
    include_deleted: bool = False,
) -> Model | None:
    query = (
        db.query(Model)
        .join(Project, Project.id == Model.project_id)
        .filter(Model.id == model_id, Project.workspace_id == workspace_id)
    )
    if not include_deleted:
        query = query.filter(Model.deleted_at.is_(None), Project.deleted_at.is_(None))
    return query.first()

