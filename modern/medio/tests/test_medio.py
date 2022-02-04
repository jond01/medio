"""Tests for `medio` module."""
from typing import Generator

import pytest

import medio


@pytest.fixture
def version() -> Generator[str, None, None]:
    """Sample pytest fixture."""
    yield medio.__version__


def test_version(version: str) -> None:
    """Sample pytest test function with the pytest fixture as an argument."""
    assert version == "0.4.1"
