"""Magic 8-Ball

Simulates the classic Magic 8-Ball toy, with some ZeroBot twists...
"""

from __future__ import annotations

import random
import re
from collections import deque
from dataclasses import dataclass
from enum import Enum, unique
from string import Template
from typing import Optional, Union

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
DEFAULT_COOLDOWN = 10

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
    def answer(cls) -> tuple['ResponseType']:
        """Return a tuple of the three answer types."""
        return cls.Positive, cls.Negative, cls.Neutral


@dataclass
class ResponsePart():
    """Represents part of an 8-Ball response."""

    text: str
    action: bool
    type: ResponseType
    expects_action: Optional[bool] = None

    def __str__(self):
        return self.format()

    def __getitem__(self, idx) -> str:
        return self.text[idx]

    def format(self):
        return f'*{self.text}*' if self.action else self.text

    def capitalize(self):
        return self.text[0].upper() + self.text[1:]


async def module_register(core):
    """Initialize mdoule."""
    global CORE, CFG, DB, recent_phrases
    CORE = core

    # TEMP: TODO: decide between monolithic modules.toml or per-feature config
    # FIXME: if going the monolithic route, check if it's loaded first
    CFG = core.load_config('modules')['Magic8Ball']
    cooldown = CFG.get('PhraseCooldown', DEFAULT_COOLDOWN)
    for rtype in ResponseType:
        recent_phrases[rtype.name] = deque(maxlen=cooldown)

    DB = await core.database_connect(MOD_ID)
    await DB.create_function('cooldown', 0, lambda: cooldown)
    await _init_database()

    _register_commands()


async def module_unregister():
    """Prepare for shutdown."""
    await CORE.database_disconnect(MOD_ID)


async def _init_database():
    await DB.executescript("""
        CREATE TABLE IF NOT EXISTS "magic8ball" (
            "response"       TEXT NOT NULL UNIQUE,
            "action"         BOOLEAN NOT NULL DEFAULT 0 CHECK(action IN (0,1)),
            "response_type"  INTEGER DEFAULT 1,
            "expects_action" BOOLEAN CHECK(expects_action IN (NULL,0,1)),
            PRIMARY KEY("response")
        ) WITHOUT ROWID;

        CREATE INDEX IF NOT EXISTS "idx_magic8ball_response_type"
        ON "magic8ball" ("response_type" ASC);
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


async def fetch_part(rtype: Union[ResponseType, tuple[ResponseType]],
                     expects_action: Optional[bool] = None) -> tuple:
    """Fetch a phrase of a particular response type."""
    if isinstance(rtype, tuple):
        placeholders = ', '.join('?' * len(rtype))
    else:
        rtype = (rtype,)
        placeholders = '?'
    last_ph = len(rtype) + 1
    results = await DB.execute(f"""
        SELECT response, action, response_type, expects_action FROM magic8ball
        WHERE response_type IN ({placeholders})
            AND CASE
                WHEN ?{last_ph} NOT NULL THEN action = ?{last_ph}
                ELSE 1
            END
        ORDER BY RANDOM() LIMIT cooldown() + 1;
    """, tuple(x.value for x in rtype) + (expects_action,))
    part = None
    rows = await results.fetchall()
    if cooldown := CFG.get('PhraseCooldown', DEFAULT_COOLDOWN):
        for row in rows:
            name = ResponseType(row['response_type']).name
            if row['response'] not in recent_phrases[name]:
                part = row
                recent_phrases[name].append(part['response'])
                break
        if part is None and len(rows) <= cooldown:
            # We have fewer phrases than the cooldown limit, so ignore it
            part = rows[0]
    else:
        part = rows[0]
    return part


def _resize_phrase_deques():
    for name in ResponseType.__members__.keys():
        new_len = CFG.get('PhraseCooldown', DEFAULT_COOLDOWN)
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
    phrase, answer = None, None

    if not re.search(r'\?[!?]*$', question):
        phrase, action, *_ = await fetch_part(ResponseType.NotAQuestion)
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
            if prelude.expects_action is not None:
                sql = 'WHERE action = ?'
                params = (prelude.expects_action,)
            else:
                sql, params = None, None
            answer = ResponsePart(*(await fetch_phrase(
                table, ['action', 'response_type'], sql, params)))
    if phrase is None:
        answer = ResponsePart(*(await fetch_part(
            ResponseType.answer(), prelude.expects_action)))

    output = f'{intro} '
    if intro.action and prelude.action and answer.action:
        output = f'*{intro.text}, {prelude.text}, then {answer.text}*'
    elif answer.action and prelude.action:
        output += f'*{prelude.capitalize()}, then {answer.text}*'
    elif answer.action:
        output += f'{prelude.capitalize()} {answer}'
    else:
        if prelude.action:
            output += f'*{prelude.capitalize()}*, it reads: {answer}'
        else:
            output += f'{prelude.capitalize()} It reads: {answer}'

    # Simplify repeat occurrances of "the 8-Ball" ...
    pat = re.compile(r'the\s+(?:magic\s+)?8-ball', flags=re.I)
    matches = list(pat.finditer(output))
    if len(matches) > 1:
        output = output[:matches[0].end()] + pat.sub('it', output[matches[0].end():])

    # ... but not in the outro, as it's a separate sentence.
    output += f'\n{outro}'
    output = Template(output).safe_substitute(
        {'zerobot': ctx.user.name, 'asker': parsed.invoker.name})

    await ctx.module_message(parsed.msg.destination, output)
