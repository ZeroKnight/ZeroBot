from pathlib import Path

import appdirs
import pytest

from ZeroBot import Core

DEFAULT_CONFIG_DIR = Path(appdirs.user_config_dir("ZeroBot", appauthor=False, roaming=True))
DEFAULT_DATA_DIR = Path(appdirs.user_data_dir("ZeroBot", appauthor=False, roaming=True))

pytest.skip("skipping core tests until hanging is fixed", allow_module_level=True)


@pytest.fixture(scope="module")
def cfg_dir(tmp_path_factory):
    return tmp_path_factory.mktemp("whatdoInamethis")


@pytest.fixture
def bot(cfg_dir):
    return Core(config_dir=cfg_dir, data_dir=cfg_dir)


@pytest.mark.xfail(reason="config tries to read non-existent config file")
def test_constructor_explicit_directories(bot, cfg_dir):
    assert (bot.config_dir, bot.data_dir) == (cfg_dir, cfg_dir)


def test_constructor_implicit_directories():
    bot = Core()
    assert (bot.config_dir, bot.data_dir) == (DEFAULT_CONFIG_DIR, DEFAULT_DATA_DIR)
