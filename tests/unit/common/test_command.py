import argparse
import itertools

import pytest

from ZeroBot.common.command import CommandParseError, CommandParser, ParsedCommand

# NOTE: As long as we're leveraging argparse, there shouldn't be a need to
#       test very much, save for our extensions to it.


class MockMessage:
    @property
    def source(self):
        return "src"

    @property
    def destination(self):
        return "dest"


@pytest.fixture
def parser():
    return CommandParser("test", "Test command")


@pytest.fixture
def cmd(parser):
    parser.add_argument("-b", "--baz", action="store_true", help="baz option")
    parser.add_argument("-B", "--biz", help="biz option")
    parser.add_argument("foo", help="foo argument")
    parser.add_argument("bar", nargs="?", help="optional bar argument")
    return parser


@pytest.fixture
def subcmd_adder_required(parser):
    return parser.make_adder(metavar="OPERATION", dest="subcmd", required=True)


@pytest.fixture
def subcmd_adder_optional(parser):
    return parser.make_adder(metavar="OPERATION", dest="subcmd", required=False)


@pytest.fixture(
    params=[
        ("subcmd_adder_required", True),
        ("subcmd_adder_optional", False),
    ]
)
def subcmd(parser, request):
    fixt, required = request.param
    adder = request.getfixturevalue(fixt)
    subparser = adder("sub", "Subcommand", aliases=["subalias1", "subalias2"])
    subparser.add_argument("-s", "--subopt1", action="store_true", help="Subcommand option")
    subparser.add_argument("-S", "--subopt2", help="Subcommand option with value")
    subparser.add_argument("subarg1", help="Subcommand argument")
    subparser.add_argument("subarg2", nargs="?", help="Optional subcommand argument")
    return (subparser, required)


def test_argparse_wrapping(parser, cmd):
    assert parser.name == parser.prog == str(parser) == "test"
    assert parser.description == "Test command"
    assert parser.usage is None
    assert not parser.add_help
    assert "arguments:" not in parser.format_help()
    assert parser.module is None


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        (["foo_val"], {"foo": "foo_val", "bar": None, "baz": False, "biz": None}),
        (["foo_val", "bar_val"], {"foo": "foo_val", "bar": "bar_val", "baz": False, "biz": None}),
        (["-b", "foo_val"], {"foo": "foo_val", "bar": None, "baz": True, "biz": None}),
        (["-b", "foo_val", "bar_val"], {"foo": "foo_val", "bar": "bar_val", "baz": True, "biz": None}),
        (["-b", "-B", "biz_val", "foo_val"], {"foo": "foo_val", "bar": None, "baz": True, "biz": "biz_val"}),
        (
            ["-b", "-B", "biz_val", "foo_val", "bar_val"],
            {"foo": "foo_val", "bar": "bar_val", "baz": True, "biz": "biz_val"},
        ),
        (["--baz", "foo_val"], {"foo": "foo_val", "bar": None, "baz": True, "biz": None}),
        (["--baz", "foo_val", "bar_val"], {"foo": "foo_val", "bar": "bar_val", "baz": True, "biz": None}),
        (["--baz", "-B", "biz_val", "foo_val"], {"foo": "foo_val", "bar": None, "baz": True, "biz": "biz_val"}),
        (
            ["--baz", "--biz", "biz_val", "foo_val", "bar_val"],
            {"foo": "foo_val", "bar": "bar_val", "baz": True, "biz": "biz_val"},
        ),
    ],
)
def test_cmd_parse(parser, cmd, args, expected):
    parsed = parser.parse_args(args)
    assert isinstance(parsed, argparse.Namespace)
    assert vars(parsed) == expected


@pytest.mark.parametrize(
    "args",
    [
        [],
        ["-b"],
        ["-B biz_val"],
        ["-b", "-B biz_val"],
    ],
)
def test_cmd_missing_arguments(parser, cmd, args):
    with pytest.raises(CommandParseError):
        parser.parse_args(args)


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        (["subarg1_val"], {"subarg1": "subarg1_val", "subarg2": None, "subopt1": False, "subopt2": None}),
        (
            ["subarg1_val", "subarg2_val"],
            {"subarg1": "subarg1_val", "subarg2": "subarg2_val", "subopt1": False, "subopt2": None},
        ),
        (["-s", "subarg1_val"], {"subarg1": "subarg1_val", "subarg2": None, "subopt1": True, "subopt2": None}),
        (
            ["-s", "subarg1_val", "subarg2_val"],
            {"subarg1": "subarg1_val", "subarg2": "subarg2_val", "subopt1": True, "subopt2": None},
        ),
        (
            ["-s", "-S", "subopt2_val", "subarg1_val", "subarg2_val"],
            {"subarg1": "subarg1_val", "subarg2": "subarg2_val", "subopt1": True, "subopt2": "subopt2_val"},
        ),
        (["--subopt1", "subarg1_val"], {"subarg1": "subarg1_val", "subarg2": None, "subopt1": True, "subopt2": None}),
        (
            ["--subopt1", "subarg1_val", "subarg2_val"],
            {"subarg1": "subarg1_val", "subarg2": "subarg2_val", "subopt1": True, "subopt2": None},
        ),
        (
            ["--subopt1", "--subopt2", "subopt2_val", "subarg1_val", "subarg2_val"],
            {"subarg1": "subarg1_val", "subarg2": "subarg2_val", "subopt1": True, "subopt2": "subopt2_val"},
        ),
    ],
)
def test_subcmd_parse(parser, subcmd, args, expected):
    subparser, required = subcmd
    for name in ("sub", "subalias1", "subalias2"):
        parsed = parser.parse_args([name] + args)
        assert isinstance(parsed, argparse.Namespace)
        assert parsed.subcmd == name
        assert vars(parsed) == {**expected, "subcmd": name}


def test_subcmd_parse_optional(parser, subcmd):
    subparser, required = subcmd
    if required:
        with pytest.raises(CommandParseError):
            parser.parse_args([])
    else:
        assert isinstance(parser.parse_args([]), argparse.Namespace)


@pytest.mark.parametrize(
    "args",
    [
        [],
        ["-s"],
        ["-s", "-S", "subopt2_val"],
        ["--subopt"],
        ["--subopt", "--subopt2", "subopt2_val"],
    ],
)
def test_subcmd_missing_arguments(parser, subcmd, args):
    subparser, required = subcmd
    with pytest.raises(CommandParseError):
        parser.parse_args(["sub"] + args)


def test_parsed_command_creation(parser, cmd):
    msg = MockMessage()
    parsed = parser.parse_args("-b -B biz_val foo_val bar_val".split())
    parsedcmd = ParsedCommand(parser.name, vars(parsed), parser, msg)

    assert parsedcmd.name == "test"
    assert parsedcmd.args == {"foo": "foo_val", "bar": "bar_val", "baz": True, "biz": "biz_val"}
    assert parsedcmd.parser == parser
    assert parsedcmd.subcmd is None
    assert isinstance(parsedcmd.msg, MockMessage)
    assert parsedcmd.invoker == msg.source == "src"
    assert parsedcmd.source == msg.destination == "dest"


@pytest.mark.xfail(reason="Need to decouple CommandHelp from Core")
def test_commandhelp_creation(parser, cmd):
    assert 0
