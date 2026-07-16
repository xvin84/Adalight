from adalight.updates import is_newer


def test_is_newer_basic():
    assert is_newer("0.4.0", "0.3.2")
    assert is_newer("1.0.0", "0.9.9")
    assert not is_newer("0.3.2", "0.3.2")
    assert not is_newer("0.3.1", "0.3.2")


def test_is_newer_with_v_prefix():
    assert is_newer("v0.4.0", "0.3.2")
    assert is_newer("0.4.0", "v0.3.2")


def test_is_newer_garbage_is_not_newer():
    assert not is_newer("beta", "0.3.2")
    assert not is_newer("", "0.3.2")
