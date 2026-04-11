from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import (
    Annotation,
    Artifact,
    Conversation,
    DataItem,
    Dataset,
    DatasetVersion,
    Embedding,
    Memory,
    MemoryEdge,
    MemoryFile,
    Message,
    Metric,
    Model,
    ModelAlias,
    ModelVersion,
    PipelineConfig,
    Project,
    TrainingJob,
    TrainingRun,
)
from app.services.storage import delete_object


@dataclass(slots=True)
class ProjectDeletionResult:
    deleted_object_keys: int = 0


class ProjectDeletionError(RuntimeError):
    def __init__(self, failed_object_keys: list[str]) -> None:
        self.failed_object_keys = failed_object_keys
        super().__init__("Failed to delete one or more project objects from storage")


def _collect_project_object_keys(db: Session, *, project_id: str) -> set[str]:
    object_keys: set[str] = set()

    for object_key, in (
        db.query(DataItem.object_key)
        .join(Dataset, Dataset.id == DataItem.dataset_id)
        .filter(Dataset.project_id == project_id)
        .all()
    ):
        if object_key:
            object_keys.add(object_key)

    for object_key, in (
        db.query(ModelVersion.artifact_object_key)
        .join(Model, Model.id == ModelVersion.model_id)
        .filter(Model.project_id == project_id)
        .all()
    ):
        if object_key:
            object_keys.add(object_key)

    for object_key, in (
        db.query(Artifact.object_key)
        .join(TrainingRun, TrainingRun.id == Artifact.run_id)
        .join(TrainingJob, TrainingJob.id == TrainingRun.training_job_id)
        .filter(TrainingJob.project_id == project_id)
        .all()
    ):
        if object_key:
            object_keys.add(object_key)

    for object_key, in (
        db.query(TrainingRun.logs_object_key)
        .join(TrainingJob, TrainingJob.id == TrainingRun.training_job_id)
        .filter(TrainingJob.project_id == project_id)
        .all()
    ):
        if object_key:
            object_keys.add(object_key)

    return object_keys


def delete_project_permanently(db: Session, *, project: Project) -> ProjectDeletionResult:
    object_keys = _collect_project_object_keys(db, project_id=project.id)
    dataset_ids = [dataset_id for dataset_id, in db.query(Dataset.id).filter(Dataset.project_id == project.id).all()]
    data_item_ids = (
        [data_item_id for data_item_id, in db.query(DataItem.id).filter(DataItem.dataset_id.in_(dataset_ids)).all()]
        if dataset_ids
        else []
    )
    model_ids = [model_id for model_id, in db.query(Model.id).filter(Model.project_id == project.id).all()]
    conversation_ids = [
        conversation_id
        for conversation_id, in db.query(Conversation.id).filter(Conversation.project_id == project.id).all()
    ]
    memory_ids = [memory_id for memory_id, in db.query(Memory.id).filter(Memory.project_id == project.id).all()]
    training_job_ids = [
        training_job_id
        for training_job_id, in db.query(TrainingJob.id).filter(TrainingJob.project_id == project.id).all()
    ]
    training_run_ids = (
        [
            training_run_id
            for training_run_id, in db.query(TrainingRun.id).filter(TrainingRun.training_job_id.in_(training_job_ids)).all()
        ]
        if training_job_ids
        else []
    )

    failed_object_keys: list[str] = []
    for object_key in sorted(object_keys):
        try:
            delete_object(bucket_name=settings.s3_private_bucket, object_key=object_key)
        except Exception:  # noqa: BLE001
            failed_object_keys.append(object_key)

    if failed_object_keys:
        raise ProjectDeletionError(failed_object_keys)

    if memory_ids:
        db.query(MemoryEdge).filter(
            (MemoryEdge.source_memory_id.in_(memory_ids)) | (MemoryEdge.target_memory_id.in_(memory_ids))
        ).delete(synchronize_session=False)
        db.query(MemoryFile).filter(MemoryFile.memory_id.in_(memory_ids)).delete(synchronize_session=False)

    db.query(Embedding).filter(Embedding.project_id == project.id).delete(synchronize_session=False)

    if conversation_ids:
        db.query(Message).filter(Message.conversation_id.in_(conversation_ids)).delete(synchronize_session=False)

    if training_run_ids:
        db.query(Artifact).filter(Artifact.run_id.in_(training_run_ids)).delete(synchronize_session=False)
        db.query(Metric).filter(Metric.run_id.in_(training_run_ids)).delete(synchronize_session=False)
        db.query(TrainingRun).filter(TrainingRun.id.in_(training_run_ids)).delete(synchronize_session=False)

    if model_ids:
        db.query(ModelAlias).filter(ModelAlias.model_id.in_(model_ids)).delete(synchronize_session=False)
        db.query(ModelVersion).filter(ModelVersion.model_id.in_(model_ids)).delete(synchronize_session=False)

    if data_item_ids:
        db.query(Annotation).filter(Annotation.data_item_id.in_(data_item_ids)).delete(synchronize_session=False)

    if dataset_ids:
        db.query(DatasetVersion).filter(DatasetVersion.dataset_id.in_(dataset_ids)).delete(synchronize_session=False)
        db.query(DataItem).filter(DataItem.dataset_id.in_(dataset_ids)).delete(synchronize_session=False)
        db.query(Dataset).filter(Dataset.id.in_(dataset_ids)).delete(synchronize_session=False)

    db.query(Memory).filter(Memory.project_id == project.id).delete(synchronize_session=False)
    db.query(Conversation).filter(Conversation.project_id == project.id).delete(synchronize_session=False)
    db.query(PipelineConfig).filter(PipelineConfig.project_id == project.id).delete(synchronize_session=False)
    db.query(TrainingJob).filter(TrainingJob.project_id == project.id).delete(synchronize_session=False)
    db.query(Model).filter(Model.project_id == project.id).delete(synchronize_session=False)
    db.delete(project)
    db.flush()
    return ProjectDeletionResult(deleted_object_keys=len(object_keys))
