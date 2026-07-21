import importlib.util
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "release_notes", _ROOT / "scripts" / "release_notes.py"
)
release_notes = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(release_notes)


def test_changelog_section_extracts_only_that_version():
    section = release_notes.changelog_section(_ROOT / "CHANGELOG.en.md", "0.22.0")
    assert "Smart port picker" in section
    # не должен утаскивать соседнюю версию
    assert "0.21.0" not in section
    assert "event bus" not in section


def test_changelog_section_missing_version_is_graceful():
    section = release_notes.changelog_section(_ROOT / "CHANGELOG.en.md", "99.0.0")
    assert section  # не падает, отдаёт заглушку


def test_build_has_both_languages_and_beta():
    body = release_notes.build("0.22.0")
    assert "## 🇬🇧 English" in body
    assert "## 🇷🇺 Русский" in body
    assert "Beta" in body and "Бета" in body
    # «что нового» из журнала попало в тело
    assert "Smart port picker" in body
    assert "Умный выбор порта" in body
    # атрибуция автора прошивки
    assert "AlexGyver" in body


def test_project_version_matches_package():
    from adalight import __version__

    assert release_notes.project_version() == __version__
