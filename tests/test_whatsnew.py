from adalight.whatsnew import notes_between, parse_changelog, update_notes

SAMPLE = """# История версий

вводный текст, не версия

## [0.14.0] — 2026-07-19

- фича A
- фича B

## [0.13.0] — 2026-07-19

- локализация

## [0.9.x] — 2026-07-17

- старое (несемвер-версия)

## [0.12.0] — 2026-07-18

- менеджер плагинов
"""


def test_parse_extracts_sections_and_skips_intro():
    entries = dict(parse_changelog(SAMPLE))
    assert set(entries) == {"0.14.0", "0.13.0", "0.9.x", "0.12.0"}
    assert "фича A" in entries["0.14.0"] and "фича B" in entries["0.14.0"]
    assert "вводный текст" not in entries["0.14.0"]


def test_notes_between_range_and_order():
    entries = parse_changelog(SAMPLE)
    picked = notes_between(entries, "0.12.0", "0.14.0")
    vers = [v for v, _ in picked]
    assert vers == ["0.14.0", "0.13.0"]  # (0.12.0, 0.14.0], новые сверху
    assert "0.12.0" not in vers  # last исключается


def test_notes_between_excludes_non_semver():
    entries = parse_changelog(SAMPLE)
    picked = notes_between(entries, "", "0.14.0")
    assert "0.9.x" not in [v for v, _ in picked]  # мусорную версию не берём


def test_update_notes_empty_last_shows_all_history():
    md = update_notes("", "0.14.0", text=SAMPLE)
    # без маркера прошлую версию не знаем → показываем всю историю до current
    assert "## 0.14.0" in md and "## 0.13.0" in md and "## 0.12.0" in md
    assert "0.9.x" not in md  # несемвер по-прежнему исключён


def test_update_notes_multi_version():
    md = update_notes("0.12.0", "0.14.0", text=SAMPLE)
    assert "## 0.14.0" in md and "## 0.13.0" in md
    assert "## 0.12.0" not in md


def test_update_notes_nothing_when_up_to_date():
    assert update_notes("0.14.0", "0.14.0", text=SAMPLE) == ""


def test_bundled_changelogs_parse():
    """Реальные CHANGELOG.md и CHANGELOG.en.md должны разбираться и содержать 0.14.0."""
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    for name in ("CHANGELOG.md", "CHANGELOG.en.md"):
        entries = dict(parse_changelog((root / name).read_text(encoding="utf-8")))
        assert "0.14.0" in entries, name
        assert entries["0.14.0"].strip()
