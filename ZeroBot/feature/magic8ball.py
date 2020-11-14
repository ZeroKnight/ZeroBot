"""Magic 8-Ball

Simulates the classic Magic 8-Ball toy, with some ZeroBot twists...
"""

import random
import re
from collections import deque
from dataclasses import dataclass
from enum import Enum, unique
from string import Template
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


@dataclass
class ResponsePart():
    """Represents part of an 8-Ball response."""

    text: str
    action: bool
    type: ResponseType

    def __str__(self):
        return self.format()

    def format(self):
        return f'*{self.text}*' if self.action else self.text


async def module_register(core):
    """Initialize mdoule."""
    global CORE, CFG, DB, recent_phrases
    CORE = core

    DB = await core.database_connect(MOD_ID)
    await DB.create_function(
        'cooldown', 0, lambda: CFG.get('PhraseCooldown', 0))
    await _init_tables()

    # TEMP: TODO: decide between monolithic modules.toml or per-feature config
    # FIXME: if going the monolithic route, check if it's loaded first
    CFG = core.load_config('modules')['Magic8Ball']
    for rtype in ResponseType:
        recent_phrases[rtype.name] = deque(maxlen=CFG.get('PhraseCooldown', 0))

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
    return row


def _resize_phrase_deques():
    for name in ResponseType.__members__.keys():
        new_len = CFG['PhraseCooldown']
        if new_len == recent_phrases[name].maxlen:
            break
        recent_phrases[name] = deque(
            recent_phrases[name].copy(), maxlen=new_len)


async def module_on_config_reloaded(ctx, name):
    """Handle `Core` config reload event."""
    if name == 'modules':
        _resize_phrase_deques()


async def module_on_config_changed(ctx, name, key, old, new):
    """Handle `Core` config change event."""
    if name == 'modules' and key == 'Magic8Ball.PhraseCooldown':
        _resize_phrase_deques()


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
            answer = ResponsePart(
                *(await fetch_phrase(table, ['action', 'response_type'])))
    if phrase is None:
        answer = ResponsePart(*(await fetch_part(ResponseType.answer())))

    output = f'{intro} ╱ '
    if intro.action and prelude.action and answer.action:
        output = f'*{intro.text}, {prelude.text}, then {answer.text}*'
    elif answer.action and prelude.action:
        output += f'*{prelude.text}, then {answer.text}*'
    elif answer.action:
        output += f'{prelude} {answer}'
    else:
        if prelude.action:
            output += f'{prelude}, it reads: {answer}'
        else:
            output += f'{prelude} It reads: {answer}'
    output += f'\n{outro}'
    output = Template(output).safe_substitute(
        {'zerobot': ctx.user.name, 'asker': parsed.invoker.name})
    await ctx.module_message(parsed.msg.destination, output)
