"""Pytest configuration — override tmp_path base to avoid Windows ACL issues."""

import pathlib

import pytest


@pytest.fixture(scope="session")
def tmp_path_factory(tmp_path_factory):
    # Redirect temp dir to a local .pytest_tmp folder the process can write to.
    return tmp_path_factory


def pytest_configure(config):
    """Point pytest's basetemp to the project-local .pytest_tmp directory."""
    # Determine project root (parent of this conftest.py's directory).
    project_root = pathlib.Path(__file__).parent.parent
    basetemp = project_root / ".pytest_tmp"
    basetemp.mkdir(exist_ok=True)

    # Only override if the user hasn't supplied --basetemp themselves.
    if not config.option.__dict__.get("basetemp"):
        config.option.basetemp = str(basetemp)
