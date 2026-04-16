# ruff: noqa: E402
import atexit, asyncio, os, shutil, tempfile
from pathlib import Path

TEST_TEMP_DIR = Path(tempfile.mkdtemp(prefix="qihang-s4-conf-pipeline-"))
atexit.register(lambda: shutil.rmtree(TEST_TEMP_DIR, ignore_errors=True))
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_TEMP_DIR / 'test.db'}"
os.environ["ENV"] = "test"

import importlib
import app.core.config as config_module
config_module.get_settings.cache_clear()
config_module.settings = config_module.get_settings()
import app.db.session as session_module
importlib.reload(session_module)

from app.services.unified_memory_pipeline import SourceType


def test_source_type_includes_study_confusion() -> None:
    # The Literal must accept "study_confusion" — if it doesn't, this
    # import would be fine but the pipeline branch logic rejects it.
    # We verify via a runtime check against the module's get_args.
    from typing import get_args
    assert "study_confusion" in get_args(SourceType)
