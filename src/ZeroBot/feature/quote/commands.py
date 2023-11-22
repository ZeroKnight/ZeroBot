"""feature/quote/commands.py

Command definitions and associated functions for the Quote feature.
"""

from __future__ import annotations

from ZeroBot.common import CommandParser

from .classes import QuoteStyle


def define_commands() -> list[CommandParser]:
    """Create our commands."""
    cmds = []
    cmd_quote = CommandParser("quote", "Recite a random quote or interact with the quote database.")
    add_subcmd = cmd_quote.make_adder(metavar="OPERATION", dest="subcmd", required=False)

    # Common arguments/options for adding quotes
    adding_options = CommandParser()
    adding_options.add_argument(
        "-d",
        "--date",
        help=(
            "Submits the quote with the following datestamp instead of the "
            "current (or deduced) date and time. **Time is interpreted as "
            "UTC.** Expects either a Unix timestamp or an ISO 8601 "
            "formatted date string."
        ),
    )
    adding_options.add_argument(
        "-s",
        "--style",
        choices=[style.name.lower() for style in QuoteStyle],
        type=str.lower,
        default="standard",
        help=(
            "Specify the quote style. The default, **standard** styles the "
            "quote like a typical IRC client message, e.g. `<Foo> hello`. "
            "**epigraph** styles the quote as in writing, e.g. "
            '`"Hello." ―Foo`. **unstyled** applies no formatting and is '
            "displayed exactly as entered."
        ),
    )
    adding_options.add_argument("-u", "--submitter", help="Submit a quote on behalf of someone else.")

    # Common arguments/options for commands that accept patterns
    pattern_options = CommandParser()
    pattern_options.add_argument(
        "-b",
        "--basic",
        action="store_true",
        help=(
            "Patterns are interpreted as simple wildcard strings rather "
            "than regular expressions. `*`, `?`, and `[...]` are "
            "supported."
        ),
    )
    pattern_options.add_argument(
        "-c",
        "--case-sensitive",
        action="store_true",
        help="Forces search pattern to be case sensitive.",
    )

    subcmd_add = add_subcmd("add", "Submit a new quote", aliases=["new"], parents=[adding_options])
    subcmd_add.add_argument(
        "author",
        help=(
            "The author of the quote, i.e. the entity being quoted. Must be "
            "wrapped in quotation marks if it contains spaces."
        ),
    )
    subcmd_add.add_argument("body", nargs="+", help="The contents of the quote")
    subcmd_add.add_argument(
        "-a",
        "--author",
        action="append",
        dest="extra_authors",
        help="Specifies additional authors for a multi-line quote",
    )
    subcmd_add.add_argument(
        "-m",
        "--multi",
        action="store_true",
        help=(
            "Create a multi-line quote. Each line may be separated with a "
            "literal newline or a `\\n` sequence. A line can be designated "
            "as an action by starting it with a `\\a` sequence."
        ),
    )

    subcmd_del = add_subcmd("del", "Remove a quote from the database", aliases=["rm", "remove", "delete"])
    subcmd_del.add_argument(
        "quote",
        nargs="+",
        help=(
            "The quote to remove. Must exactly match the body of a quote. "
            "If the `id` option is used, this is the desired quote ID."
        ),
    )
    subcmd_del.add_argument(
        "-i",
        "--id",
        action="store_true",
        help="Specify the target quote by ID instead.",
    )
    # TBD: Maybe not include this and just do such replaces in SQL by hand.
    # subcmd_del.add_argument(
    #     '-r', '--regex', action='store_true',
    #     help=('The `quote` argument is interpreted as a regular expression '
    #           'and all matching quotes will be removed. Use with caution!'))

    subcmd_recent = add_subcmd("recent", "Display the most recently added quotes", parents=[pattern_options])
    subcmd_recent.add_argument(
        "pattern",
        nargs="?",
        help=(
            "Show the most recent quotes by the author matching the given "
            "pattern. If omitted, shows the most recently added quotes "
            "instead."
        ),
    )
    subcmd_recent.add_argument(
        "-n",
        "--count",
        type=int,
        default=1,
        help="Display the `n` most recent quotes. Defaults to 1, with 5 being the maximum.",
    )
    subcmd_recent.add_argument(
        "-u",
        "--submitter",
        action="store_true",
        help="Show the most recent quotes by submitter instead of by author.",
    )

    subcmd_search = add_subcmd(
        "search",
        "Search the quote database for a specific quote",
        aliases=["find"],
        parents=[pattern_options],
    )
    subcmd_search.add_argument(
        "pattern",
        nargs="*",
        help=(
            "The search pattern used to match quote body content. If the "
            "pattern contains spaces, they must be escaped or the pattern "
            "must be wrapped in quotation marks."
        ),
    )
    subcmd_search.add_argument(
        "-a",
        "--author",
        help=(
            "Filter results to the author matching this pattern. The "
            "`pattern` argument may be omitted if this option is given."
        ),
    )
    subcmd_search.add_argument("-i", "--id", type=int, help="Fetch the quote with the given ID.")
    subcmd_search.add_argument(
        "-n",
        "--count",
        action="store_true",
        help="Return the number of quotes matching the given query instead.",
    )
    subcmd_search.add_argument(
        "-u",
        "--submitter",
        help=(
            "Filter results to the submitter matching this pattern. The "
            "`pattern` argument may be omitted if this option is given."
        ),
    )

    subcmd_stats = add_subcmd("stats", "Query various statistics about the quote database.")
    subcmd_stats.add_argument(
        "user",
        nargs="?",
        help="Retrieve stats for the given user. If omitted, return stats for yourself.",
    )
    subcmd_stats.add_argument(
        "-g",
        "--global",
        action="store_true",
        help="Retrieve general stats about the quote database as a whole.",
    )
    subcmd_stats.add_argument(
        "-l",
        "--leaderboard",
        "--top",
        action="store_true",
        help="Shows the top users for the chosen criteria.",
    )
    subcmd_stats.add_argument(
        "-n",
        "--count",
        type=int,
        default=3,
        help="Influences the number of results displayed. Defaults to 3.",
    )
    subcmd_stats.add_argument(
        "-s",
        "--sort",
        help=(
            "Determines how the stats output should be sorted. This option "
            "expects a comma-delimited list of criteria to sort on, where "
            "each criteria is given as its respective option short name. "
            "Ex: `--sort q,u` to sort by quotes, then submissions."
        ),
    )
    subcmd_stats.add_argument(
        "-q",
        "--quotes",
        action="store_true",
        help="Show total number of quotes in stats output.",
    )
    subcmd_stats.add_argument(
        "-u",
        "--submissions",
        action="store_true",
        help="Show total number of submissions in stats output.",
    )
    subcmd_stats.add_argument(
        "-e",
        "--self-submissions",
        action="store_true",
        help="Show total number of self-submitted quotes in stats output.",
    )
    subcmd_stats.add_argument(
        "-p",
        "--percent",
        action="store_true",
        help="Show percentage of database totals for displayed criteria.",
    )
    subcmd_stats.add_argument(
        "-y",
        "--per-year",
        action="store_true",
        help="Show number per year for displayed criteria.",
    )

    subcmd_quick = add_subcmd(
        "quick",
        "Shortcut to quickly add a quote of the last thing someone said "
        "or create one automatically from an existing message.",
        aliases=["grab"],
        parents=[adding_options],
    )
    subcmd_quick_group = subcmd_quick.add_mutually_exclusive_group()
    subcmd_quick_group.add_argument(
        "user",
        nargs="?",
        help="The user to quote. If omitted, will quote the last message in the channel.",
    )
    subcmd_quick_group.add_argument(
        "-i",
        "--id",
        type=int,
        help=(
            "For protocols that support it (like Discord), specify a "
            "message ID to add a quote automatically. Determines author, "
            "body, and date/time from the message data."
        ),
    )
    subcmd_quick.add_argument(
        "-n",
        "--num-previous",
        type=int,
        default=0,
        help="Include `n` messages before the target messsage to make a multi-line quote.",
    )

    cmds.append(cmd_quote)
    return cmds
