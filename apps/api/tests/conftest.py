from __future__ import annotations

import importlib
import os
from pathlib import Path
from types import ModuleType

import pytest


_CURRENT_DATABASE_URL: str | None = None

_APP_RUNTIME_MODULES = (
    "app.core.deps",
    "app.core.entitlements",
    "app.core.notebook_access",
    "app.routers.utils",
    "app.routers.ai_actions",
    "app.routers.attachments",
    "app.routers.auth",
    "app.routers.billing",
    "app.routers.blocks",
    "app.routers.chat",
    "app.routers.datasets",
    "app.routers.digest",
    "app.routers.memory",
    "app.routers.memory_stream",
    "app.routers.model_catalog",
    "app.routers.models",
    "app.routers.notebook_ai",
    "app.routers.notebooks",
    "app.routers.pipeline",
    "app.routers.proactive",
    "app.routers.projects",
    "app.routers.search",
    "app.routers.study",
    "app.routers.study_ai",
    "app.routers.study_decks",
    "app.routers.uploads",
    "app.services.composed_realtime",
    "app.routers.realtime",
    "app.main",
)


def _database_url_for_module(module: ModuleType) -> str | None:
    db_path = getattr(module, "DB_PATH", None)
    if db_path is not None:
        return f"sqlite:///{Path(db_path)}"

    temp_dir = getattr(module, "TEST_TEMP_DIR", None)
    if temp_dir is not None:
        return f"sqlite:///{Path(temp_dir) / 'test.db'}"

    return None


def _module_uses_fastapi_app(module: ModuleType) -> bool:
    if hasattr(module, "main_module"):
        return True
    return any(
        name.endswith("_router")
        and isinstance(value, ModuleType)
        and value.__name__.startswith("app.routers.")
        for name, value in vars(module).items()
    )


def _reload_database_runtime(database_url: str, *, include_app: bool) -> None:
    global _CURRENT_DATABASE_URL

    os.environ["DATABASE_URL"] = database_url

    import app.core.config as config_module
    import app.db.session as session_module

    config_module.get_settings.cache_clear()
    config_module.settings = config_module.get_settings()
    importlib.reload(session_module)

    if include_app:
        for module_name in _APP_RUNTIME_MODULES:
            importlib.reload(importlib.import_module(module_name))

    _CURRENT_DATABASE_URL = database_url


def _rebind_test_module_globals(module: ModuleType) -> None:
    import app.core.config as config_module
    import app.db.session as session_module

    if hasattr(module, "engine"):
        module.engine = session_module.engine
    if hasattr(module, "SessionLocal"):
        module.SessionLocal = session_module.SessionLocal
    if hasattr(module, "settings"):
        module.settings = config_module.settings
    if hasattr(module, "main_module"):
        module.main_module = importlib.import_module("app.main")

    for name, value in list(vars(module).items()):
        if (
            name.endswith("_router")
            and isinstance(value, ModuleType)
            and value.__name__.startswith("app.routers.")
        ):
            setattr(module, name, importlib.import_module(value.__name__))


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_setup(item: pytest.Item) -> None:
    module = item.module
    database_url = _database_url_for_module(module)
    if database_url is None:
        return

    include_app = _module_uses_fastapi_app(module)
    if database_url != _CURRENT_DATABASE_URL:
        _reload_database_runtime(database_url, include_app=include_app)

    _rebind_test_module_globals(module)
