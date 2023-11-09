import pytest

from ZeroBot.common.enums import ConfigCmdStatus, ModuleCmdStatus


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("LOAD_OK", [True, False]),
        ("RELOAD_OK", [True, True]),
        ("LOAD_FAIL", [False, False]),
        ("RELOAD_FAIL", [False, True]),
        ("NO_SUCH_MOD", [False, False]),
        ("ALREADY_LOADED", [False, False]),
        ("NOT_YET_LOADED", [False, True]),
        ("QUERY", [False, False]),
    ],
)
def test_modulecmdstatus(status, expected):
    s = getattr(ModuleCmdStatus, status)
    expected_ok, expected_reload = expected
    assert ModuleCmdStatus.is_ok(s) == expected_ok
    assert ModuleCmdStatus.is_reload(s) == expected_reload


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("GET_OK", True),
        ("SET_OK", True),
        ("RESET_OK", True),
        ("SAVE_OK", True),
        ("RELOAD_OK", True),
        ("NO_SUCH_KEY", False),
        ("NO_SUCH_CONFIG", False),
        ("SAVE_FAIL", False),
        ("RELOAD_FAIL", False),
    ],
)
def test_configcmdstatus_ok(status, expected):
    assert ConfigCmdStatus.is_ok(getattr(ConfigCmdStatus, status)) == expected
