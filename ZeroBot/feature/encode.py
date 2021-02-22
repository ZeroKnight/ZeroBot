"""Encode

Utility feature to hash, encode, and decode arbitrary input with a suite of
algorithms and encodings.
"""

import base64
import codecs
import crypt
import hashlib
import logging
import string
from binascii import crc32
from io import StringIO
from typing import Optional, Tuple
from zlib import adler32

from ZeroBot.common import CommandParser

MODULE_NAME = 'Encode'
MODULE_AUTHOR = 'ZeroKnight'
MODULE_VERSION = '0.2'
MODULE_LICENSE = 'MIT'
MODULE_DESC = ('Utility feature to hash, encode, or decode arbitrary input '
               'with a suite of algorithms and encodings.')

CORE = None
CFG = None
MOD_ID = __name__.rsplit('.', 1)[-1]

logger = logging.getLogger('ZeroBot.Feature.Encode')


def algo_parts(name: str) -> Tuple[str, Optional[int]]:
    """Return a tuple of an algorithm's name and optional number suffix.

    Example::
        >>> algo_parts('rot13')
        ('rot', 13)
        >>> algo_parts('whirlpool')
        ('whirlpool', None)
    """
    base_algo = name.rstrip('0123456789')
    try:
        bits = int(name[len(base_algo):])
    except ValueError:
        bits = None
    return base_algo, bits


def rot_encode(data: str, n: int = 13) -> str:
    """ROT-encode the given string, shifting `n` places."""
    if not 1 <= n < 26:
        raise ValueError('n must be in range [1, 26)')
    with StringIO() as digest:
        for char in data:
            if char in string.ascii_letters:
                case = (string.ascii_lowercase
                        if char.islower() else string.ascii_uppercase)
                digest.write(case[(case.index(char) + n) % 26])
            else:
                digest.write(char)
        return digest.getvalue()


def rot_decode(data: str, n: int = 13) -> str:
    """Decode a ROT-encoded string that was shifted by `n` places."""
    if not 1 <= n < 26:
        raise ValueError('n must be in range [1, 26)')
    return rot_encode(data, 26 - n)


def sumn(data: str, n: int = 16) -> int:
    """Calculate a "sum" checksum, e.g. sum24, sum32, etc."""
    if n < 1:
        raise ValueError('n must be greater than 0')
    result = 0
    for char in data:
        result += ord(char) & 0xFF
    return hex(result % 2**n)


encoders = {
    'crc32': lambda x: crc32(x.encode()),
    'rot': rot_encode,
    'sum': sumn
}

# BaseX algorithms
for radix in (16, 32, 64, 85):
    func = getattr(base64, f'b{radix}encode')
    encoders[f'base{radix}'] = lambda x, func=func: func(x.encode()).decode()
encoders['ascii85'] = lambda x: base64.a85encode(x.encode()).decode()

# Assorted hashlib algorithms
encoders.update({
    name: (lambda x, name=name: hashlib.new(name, x.encode()).hexdigest())
    for name in hashlib.algorithms_available
    if not name.startswith('shake')  # TODO: support this
})

# Misc
encoders['adler32'] = adler32
encoders['blowfish'] = (
    lambda x: crypt.crypt(x, crypt.mksalt(crypt.METHOD_BLOWFISH)))
encoders['uu'] = lambda x: codecs.encode(x.encode(), 'uu').decode()

decoders = {
    'rot': rot_decode,
    'uu': lambda x: codecs.decode(x.encode(), 'uu').decode()
}

# BaseX algorithms
for radix in (16, 32, 64, 85):
    func = getattr(base64, f'b{radix}decode')
    decoders[f'base{radix}'] = lambda x, func=func: func(x).decode()
decoders['ascii85'] = lambda x: base64.a85decode(x).decode()


async def module_register(core):
    """Initialize module."""
    global CORE, CFG
    CORE = core

    # TEMP: TODO: decide between monolithic modules.toml or per-feature config
    CFG = core.load_config('modules').get(MODULE_NAME)

    _register_commands()


def _register_commands():
    """Create and register our commands."""
    cmds = []
    transform_args = CommandParser()
    transform_args.add_argument(
        'algorithm', help='The algorithm to use.')
    transform_args.add_argument(
        'input', nargs='+', help='The string to transform.')

    cmd_encode = CommandParser(
        'encode', 'Encode a string.', parents=[transform_args])
    case_opts = cmd_encode.add_mutually_exclusive_group(required=False)
    case_opts.add_argument(
        '-c', '--lowercase', action='store_const', const=str.lower,
        dest='case_func', default=lambda x: x,
        help='Output digest in lowercase.')
    case_opts.add_argument(
        '-C', '--uppercase', action='store_const', const=str.upper,
        dest='case_func', default=lambda x: x,
        help='Output digest in uppercase.')
    cmds.append(cmd_encode)

    cmd_decode = CommandParser(
        'decode', 'Decode a string.', parents=[transform_args])
    cmds.append(cmd_decode)

    cmd_algorithms = CommandParser(
        'algorithms', 'List supported algorithms for encoding/decoding.')
    cmds.append(cmd_algorithms)

    CORE.command_register(MOD_ID, *cmds)


async def module_command_encode(ctx, parsed):
    """Handle `encode` command."""
    await handle_transform(ctx, parsed, encoders)


async def module_command_decode(ctx, parsed):
    """Handle `decode` command."""
    await handle_transform(ctx, parsed, decoders)


async def handle_transform(ctx, parsed, method):
    algo = parsed.args['algorithm']
    data = ' '.join(parsed.args['input'])
    case = parsed.args.get('case_func')
    # TODO: options

    try:
        xcoder = method[algo]
    except KeyError:
        try:
            # If given 'rot13', try 'rot'
            base_algo, suffix = algo_parts(algo)
            xcoder = method[base_algo]
            args = (data, suffix)
        except KeyError:
            await ctx.reply_command_result(
                parsed, "I don't know that algorithm...")
    else:
        args = (data,)
    try:
        digest = xcoder(*args)
        if case is not None:
            digest = case(digest)
    except Exception:  # pylint: disable=broad-except
        await CORE.module_send_event('invalid_command', ctx, parsed.msg)
        return
    await ctx.reply_command_result(parsed, digest)


async def module_command_algorithms(ctx, parsed):
    """Handle `algorithms` command."""
    lines = ['**Available Encoders**']
    lines.append(', '.join(encoder for encoder in sorted(encoders)))
    lines.append('\n**Available Decoders**')
    lines.append(', '.join(decoder for decoder in sorted(decoders)))
    await ctx.module_message(parsed.source, '\n'.join(lines))
