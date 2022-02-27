from string import ascii_letters, punctuation, digits

import pytest

from ZeroBot import util

LIST10 = list(range(10))


@pytest.fixture
def nested_dict():
    return {
        "foo": {
            "bar": {
                "baz": 4.2,
                "buzz": "cat",
            },
            "biz": 2,
        },
        "bang": 1,
    }


@pytest.mark.parametrize(
    "key,expected",
    [
        (["bang"], 1),
        (["foo", "biz"], 2),
        (["foo", "bar", "baz"], 4.2),
        (["foo", "bar", "buzz"], "cat"),
        ("bang", 1),
        ("foo.biz", 2),
        ("foo.bar.baz", 4.2),
        ("foo.bar.buzz", "cat"),
        ("foo.bar", {"baz": 4.2, "buzz": "cat"}),
    ],
)
def test_map_reduce_valid(key, expected, nested_dict):
    assert util.map_reduce(key, nested_dict) == expected


@pytest.mark.parametrize(
    "key", ["missing", "foo.missing", "foo.bar.missing", ["missing"], ["foo", "missing"], ["foo", "bar", "missing"]]
)
def test_map_reduce_invalid(key, nested_dict):
    with pytest.raises(KeyError):
        util.map_reduce(key, nested_dict)


@pytest.mark.parametrize(
    "iterable",
    [
        LIST10,
        [LIST10],
        [[0, 1], [2, 3], [4, 5], [6, 7], [8, 9]],
        [0, 1, 2, [3, 4], 5, [6, 7, 8], 9],
        [0, 1, [2, 3, [4, 5]], [6, [7, 8], 9]],
        [[0, 1, [2, 3], [4, 5], [6, [7, [8, 9]]]]],
    ],
)
def test_flatten(iterable):
    assert list(util.flatten(iterable)) == LIST10


@pytest.mark.parametrize(
    "s,expected",
    [
        ("foo", ["foo"]),
        ('"foo"', ["foo"]),
        (r"\"foo\"", ['"foo"']),
        ('"foo bar baz"', ["foo bar baz"]),
        ("foo bar baz", ["foo", "bar", "baz"]),
        ('foo "bar baz"', ["foo", "bar baz"]),
        (r'foo "bar baz" \"buzz\" bang', ["foo", "bar baz", '"buzz"', "bang"]),
        (r'foo "\"bar baz\"" buzz', ["foo", '"bar baz"', "buzz"]),
        (r"foo bar\ baz", ["foo", "bar baz"]),
        (r"foo bar \baz", ["foo", "bar", r"\baz"]),
        ("foo bar baz\\", ["foo", "bar", "baz\\"]),
    ],
)
def test_shellish_split(s, expected):
    assert util.shellish_split(s) == expected


def test_shellish_split_non_special_escapes():
    punct = punctuation.translate(str.maketrans({'"': None, "\\": None}))
    for char in ascii_letters + digits + punct:
        assert util.shellish_split(f"\\{char}") == [f"\\{char}"]


@pytest.mark.parametrize("s", ['"foo bar baz', 'foo "bar baz', 'foo bar baz"'])
def test_shellish_split_unclosed_quote(s):
    with pytest.raises(ValueError, match="Unclosed quote"):
        assert util.shellish_split(s)
