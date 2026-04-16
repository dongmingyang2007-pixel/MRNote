# ruff: noqa: E402
import atexit, os, shutil, tempfile
from pathlib import Path

TEST_TEMP_DIR = Path(tempfile.mkdtemp(prefix="qihang-s4-models-"))
atexit.register(lambda: shutil.rmtree(TEST_TEMP_DIR, ignore_errors=True))
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_TEMP_DIR / 'test.db'}"
os.environ["ENV"] = "test"

import importlib
import app.core.config as config_module
config_module.get_settings.cache_clear()
config_module.settings = config_module.get_settings()
import app.db.session as session_module
importlib.reload(session_module)

from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.models import (
    Notebook, NotebookPage, Project, StudyCard, StudyDeck, User, Workspace,
)


def setup_function() -> None:
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def _seed() -> str:
    with SessionLocal() as db:
        ws = Workspace(name="W"); user = User(email="u@x.co", password_hash="x")
        db.add(ws); db.add(user); db.commit(); db.refresh(ws); db.refresh(user)
        pr = Project(workspace_id=ws.id, name="P"); db.add(pr); db.commit(); db.refresh(pr)
        nb = Notebook(workspace_id=ws.id, project_id=pr.id, created_by=user.id,
                      title="NB", slug="nb")
        db.add(nb); db.commit(); db.refresh(nb)
        return nb.id, user.id


def test_deck_and_card_roundtrip() -> None:
    nb_id, user_id = _seed()
    with SessionLocal() as db:
        deck = StudyDeck(notebook_id=nb_id, name="My deck", created_by=user_id)
        db.add(deck); db.commit(); db.refresh(deck)

        card = StudyCard(
            deck_id=deck.id, front="Q", back="A",
            source_type="manual",
        )
        db.add(card); db.commit(); db.refresh(card)

        # Defaults
        assert card.difficulty == 5.0
        assert card.stability == 0.0
        assert card.review_count == 0
        assert card.consecutive_failures == 0
        assert card.confusion_memory_written_at is None
        assert card.next_review_at is None
