"""Unit tests for the language registry."""

from critique.languages import (
    CPP,
    PYTHON,
    SUPPORTED_EXTENSIONS,
    detect_language,
    is_supported,
    language_for_key,
)


def test_detects_python():
    assert detect_language("foo/bar.py") is PYTHON
    assert detect_language("BAR.PY") is PYTHON  # case-insensitive


def test_detects_cpp_variants():
    for path in ("a.c", "a.h", "a.cc", "a.cpp", "a.cxx", "a.hpp", "a.hh", "a.ino"):
        assert detect_language(path) is CPP, path


def test_unsupported_returns_none():
    assert detect_language("notes.txt") is None
    assert detect_language("Makefile") is None


def test_is_supported():
    assert is_supported("main.cpp")
    assert is_supported("script.py")
    assert not is_supported("data.json")


def test_supported_extensions_cover_both_languages():
    assert ".py" in SUPPORTED_EXTENSIONS
    assert ".cpp" in SUPPORTED_EXTENSIONS
    assert ".h" in SUPPORTED_EXTENSIONS


def test_language_for_key():
    assert language_for_key("python") is PYTHON
    assert language_for_key("cpp") is CPP
    assert language_for_key("rust") is None
