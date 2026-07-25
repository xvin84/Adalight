"""udev-правило для доступа к порту на Linux: контент, проверка, команды."""

from pathlib import Path

from adalight import udev

ROOT = Path(__file__).resolve().parent.parent


def test_rule_content_matches_packaged_file():
    """Правило в поставке (packaging/) не должно разъезжаться с кодом."""
    packaged = (ROOT / "packaging" / udev.RULES_FILENAME).read_text(encoding="utf-8")
    assert packaged == udev.RULES_CONTENT


def test_rule_covers_known_vendors_via_uaccess():
    for vendor in ("1a86", "10c4", "0403", "303a"):
        assert f'ATTRS{{idVendor}}=="{vendor}"' in udev.RULES_CONTENT
    # ключевой механизм: права выдаёт logind пользователю сессии, без групп
    assert udev.RULES_CONTENT.count('MODE="0660", TAG+="uaccess"') == 4
    assert 'SUBSYSTEM=="tty"' in udev.RULES_CONTENT


def test_is_rule_installed(tmp_path):
    p = tmp_path / udev.RULES_FILENAME
    assert not udev.is_rule_installed(p)
    p.write_text(udev.RULES_CONTENT, encoding="utf-8")
    assert udev.is_rule_installed(p)


def test_manual_command_is_complete():
    cmd = udev.manual_command()
    assert str(udev.RULES_PATH) in cmd
    assert "udevadm control --reload-rules" in cmd
    assert "udevadm trigger" in cmd
    assert 'ATTRS{idVendor}=="1a86"' in cmd  # правило целиком внутри команды


def test_group_fallback_hint_mentions_dialout():
    assert "dialout" in udev.group_fallback_hint()
