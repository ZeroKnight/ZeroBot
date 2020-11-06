"""Magic 8-Ball

Simulates the classic Magic 8-Ball toy, with some ZeroBot twists...
"""

import random
import re
from collections import deque, namedtuple
from enum import Enum, unique
from typing import Tuple, Union

from ZeroBot.common import CommandParser

MODULE_NAME = 'Magic 8-Ball'
MODULE_AUTHOR = 'ZeroKnight'
MODULE_VERSION = '0.2'
MODULE_LICENSE = 'MIT'
MODULE_DESC = ('Simulates the classic Magic 8-Ball toy, with some ZeroBot '
               'twists...')

CORE = None
CFG = None
DB = None
MOD_ID = __name__.rsplit('.', 1)[-1]

CLASSIC_PHRASES = [
    'It is certain',
    'It is decidedly so',
    'Without a doubt',
    'Yes definitely',
    'You may rely on it',
    'As I see it, yes',
    'Most likely',
    'Outlook good',
    'Yes',
    'Signs point to yes',
    'Reply hazy try again',
    'Ask again later',
    'Better not tell you now',
    'Cannot predict now',
    'Concentrate and ask again',
    "Don't count on it",
    'My reply is no',
    'My sources say no',
    'Outlook not so good',
    'Very doubtful'
]

recent_phrases = {}

ResponsePart = namedtuple('ResponsePart', 'phrase, action')


@unique
class ResponseType(Enum):
    Positive = 1
    Negative = 2
    Neutral = 3
    Intro = 4
    Prelude = 5
    Outro = 6
    NotAQuestion = 7

    @classmethod
    def answer(cls) -> Tuple['ResponseType']:
        """Return a tuple of the three answer types."""
        return cls.Positive, cls.Negative, cls.Neutral


async def module_register(core):
    """Initialize mdoule."""
    global CORE, CFG, DB, recent_phrases
    CORE = core

    DB = await core.database_connect(MOD_ID)
    await DB.create_function('cooldown', 0, lambda: CFG['PhraseCooldown'])
    await _init_tables()

    # TEMP: TODO: decide between monolithic modules.toml or per-feature config
    # FIXME: if going the monolithic route, check if it's loaded first
    CFG = core.load_config('modules')['Magic8Ball']
    for rtype in ResponseType:
        recent_phrases[rtype.name] = deque(maxlen=CFG['PhraseCooldown'])

    _register_commands()


async def module_unregister():
    """Prepare for shutdown."""
    await CORE.database_disconnect(MOD_ID)


async def _init_tables():
    await DB.execute("""
        CREATE TABLE IF NOT EXISTS "magic8ball" (
            "response"      TEXT NOT NULL UNIQUE,
            "action"        BOOLEAN NOT NULL DEFAULT 0 CHECK(action IN (0,1)),
            "response_type" INTEGER DEFAULT 1,
            PRIMARY KEY("response")
        ) WITHOUT ROWID
    """)


def _register_commands():
    """Create and register our commands."""
    cmds = []
    cmd_8ball = CommandParser(
        '8ball',
        "Shake ZeroBot's 8-Ball and receive an answer to your desires")
    cmd_8ball.add_argument('question', nargs='+', help='Your burning question')
    cmds.append(cmd_8ball)

    CORE.command_register(MOD_ID, *cmds)


async def fetch_part(rtype: Union[ResponseType, Tuple[ResponseType]]) -> Tuple:
    """Fetch a phrase of a particular response type."""
    if isinstance(rtype, tuple):
        placeholders = ', '.join('?' * len(rtype))
    else:
        rtype = (rtype,)
        placeholders = '?'
    results = await DB.execute(f"""
        SELECT response, action, response_type FROM magic8ball
        WHERE response_type IN ({placeholders})
        ORDER BY RANDOM() LIMIT cooldown() + 1;
    """, tuple(x.value for x in rtype))
    row = await results.fetchone()
    name = ResponseType(row[2]).name
    while row[0] in recent_phrases[name]:
        row = await results.fetchone()
    recent_phrases[name].append(row[0])
    return row[:2]


async def module_command_8ball(ctx, parsed):
    """Handle `8ball` command."""
    question = ' '.join(parsed.args['question'])
    phrase = None

    if not re.search(r'\?[!?]*$', question):
        phrase, action = await fetch_part(ResponseType.NotAQuestion)
        await ctx.module_message(parsed.msg.destination, phrase, action)
        return

    intro = ResponsePart(*(await fetch_part(ResponseType.Intro)))
    prelude = ResponsePart(*(await fetch_part(ResponseType.Prelude)))
    outro = ResponsePart(*(await fetch_part(ResponseType.Outro)))

    integrate = CFG['IntegrateChat']
    if integrate['Enabled'] and CORE.feature_loaded('chat'):
        from ZeroBot.feature.chat import fetch_phrase
        weight_q = integrate['Weights.Questioned']
        weight_n = integrate['Weights.None']
        table = random.choices(
            ['questioned', None], [weight_q, weight_n])[0]
        if table:
            answer = ResponsePart(*(await fetch_phrase(table, ['action'])))
    if phrase is None:
        answer = ResponsePart(*(await fetch_part(ResponseType.answer())))

    parts = []
    parts.append(f'*{intro.phrase}*.' if intro.action else intro.phrase)
    parts.append(f'*{prelude.phrase}*,' if prelude.action else prelude.phrase)
    if answer.action:
        join = 'then ' if prelude.action else ''
        parts.append(f'{join}*{answer.phrase}*.')
    else:
        join = 'the 8-Ball reads: '
        if prelude.action:
            join.capitalize()
        parts.append(f'{join}{answer.phrase}')
    parts.append(f'*{outro.phrase}*' if outro.action else outro.phrase)
    await ctx.module_message(parsed.msg.destination, ' '.join(parts))
