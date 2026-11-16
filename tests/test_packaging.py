import importlib.util
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "build_release", Path(__file__).resolve().parents[1] / "packaging" / "build_release.py")
build_release = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(build_release)
release_version = build_release.release_version


def test_dev_builds_never_look_like_releases():
    assert release_version("0.2.0", None, "abc1234") == "0.2.0-dev-abc1234"
    assert release_version("0.2.0", None, None) == "0.2.0-dev"


def test_release_tags_need_the_v_and_the_pyproject_version():
    assert release_version("0.2.0", "v0.2.0", "abc1234") == "0.2.0"
    assert release_version("0.2.0", "v0.2.0-rc1", None) == "0.2.0-rc1"
    for bad in ("0.2.0", "v0.3.0", "v0.2.0-", "v0.2", "release-0.2.0"):
        with pytest.raises(SystemExit):
            release_version("0.2.0", bad, None)


def test_version_comes_from_pyproject():
    assert build_release.project_version().count(".") == 2
