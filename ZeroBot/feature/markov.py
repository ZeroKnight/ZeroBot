"""Markov

Grants ZeroBot the ability to generate sentences built from a simple Markov
chain either automatically or on demand. The backing source is typically prior
messages from channels that ZeroBot inhabits, but data from external sources
may also be added.
"""

from __future__ import annotations

import gzip
import logging
import pickle
import random
import re
from collections import deque
from functools import partial
from io import StringIO
from itertools import repeat
from pathlib import Path
from typing import (AsyncGenerator, Dict, Generator, List, Optional, Tuple,
                    Union)
from urllib.parse import urlparse

from ZeroBot.common import CommandParser
from ZeroBot.database import get_participant as getpart
from ZeroBot.database import get_source as getsrc

MODULE_NAME = 'Markov'
MODULE_AUTHOR = 'ZeroKnight'
MODULE_VERSION = '0.1'
MODULE_LICENSE = 'MIT'
MODULE_DESC = 'Markov chain powered sentence generator'

CORE = None
CFG = None
DB = None
MOD_ID = __name__.rsplit('.', 1)[-1]
get_participant = None
get_source = None

logger = logging.getLogger('ZeroBot.Feature.Markov')

CHAIN = None
TOKENIZERS = None
DEFAULT_DUMP_PATH = None


# TODO: if a markov request was generated naturally (asking zerobot what's on
# his mind, he chooses to at random, etc.) and we're on discord, send
# a "typing" event and wait for 1.0-3.0 seconds before sending

# TODO: method to "hot insert" a new line into the corpus and state_map
# TODO: method to pre-compute state weights like markovify
class MarkovSentenceGenerator:
    """An *m*-order Markov chain for generating sentences.

    Parameters
    ----------
    corpus : Corpus
        The corpus of text that the chain should be built on. It should be
        a list of lists, where each outer list is a line from the corpus, and
        each inner list consists of each token of the line.
    order : int
        Creates a Markov chain of the given order. A typical value is either
        1 or 2, with the latter tending to create less haphazard sentences.
        **N.B.** Higher orders tend to create sentences very similar to the
        chain's input, unless the corpus is particularly large.
    state_map : ChainModel, optional
        A pre-built state map.
    """

    SENTENCE_BEGIN = '___ZB_MARKOV_SENTENCE_BEGIN___'
    SENTENCE_END = '___ZB_MARKOV_SENTENCE_END___'

    # Type aliases
    Corpus = List[List[str]]
    Token = Union[type(SENTENCE_BEGIN), type(SENTENCE_END), str]
    ChainState = Tuple[Token, ...]
    ChainModel = Dict[ChainState, Dict[Token, int]]

    def __init__(self, corpus: Corpus, order: int = 1,
                 state_map: ChainModel = None):
        if order < 1:
            raise ValueError('Chain order must be at least 1')
        self._order = order
        self.corpus = corpus
        if state_map is None:
            self.state_map = self.build(corpus)
        else:
            self.state_map = state_map

    def __iter__(self):
        return self.sentence_gen()

    @property
    def order(self) -> int:
        """The order of this Markov chain.

        Represents the number of previous states used to transition to the next
        state. Modifying this attribute will rebuild the chain's state model.

        Notes
        -----
        A chain with an order of 2 considers the last two words when
        determining the next state. For example, a sequence like "foo bar"
        might be followed by "baz", "biz", or "buzz", but "foo biz" could have
        a completely different set of possible following words.
        """
        return self._order

    @order.setter
    def order(self, new_order: int):
        if new_order == self._order:
            return
        if new_order < 1:
            raise ValueError('Chain order must be at least 1')
        self._order = new_order
        self.state_map = self.build(self.corpus)

    @staticmethod
    def format_sentence(tokens: list[str]) -> str:
        """Return a formatted sentence from the given tokens."""
        with StringIO() as sentence:
            for token in tokens:
                if token in '.,;!?':
                    sentence.seek(max(0, sentence.tell() - 1))
                sentence.write(f'{token} ')
            return sentence.getvalue().strip()

    @classmethod
    def from_dump(cls, file) -> MarkovSentenceGenerator:
        """Documentation for from_dump

        Parameters
        ----------
        file
            An open file object to read the dumped chain from.
        """
        return pickle.load(file)

    def dump(self, file):
        """Dump a serialized representation of the chain to disk.

        Parameters
        ----------
        file
            An open file object to dump the chain to.
        """
        pickle.dump(self, file)

    def build(self, corpus: Corpus) -> ChainModel:
        """Build a chain's state map based on the given corpus.

        Parameters
        ----------
        corpus : Corpus
            The corpus of text that the chain should be built on.

        Returns
        -------
        ChainModel
            The resultant state map.
        """
        state_map = {}
        for line in corpus:
            tokens = ([self.SENTENCE_BEGIN] * self._order
                      + line
                      + [self.SENTENCE_END])
            for i in range(len(tokens) - self._order):
                token_seq = tuple(tokens[i:i + self._order])
                next_token = tokens[i + self._order]
                try:
                    edges = state_map.setdefault(token_seq, {})
                    edges[next_token] += 1
                except KeyError:
                    edges[next_token] = 1
        return state_map

    def rebuild(self):
        """Rebuild the chain's state map from the current corpus."""
        self.state_map = self.build(self.corpus)

    def transition(self, state: ChainState) -> str:
        """Return the next word following the given state.

        The next word is chosen at random from all possible next words,
        weighted by their occurrence.

        Parameters
        ----------
        state : ChainState
            The state to transition from.

        Returns
        -------
        str
            A randomly chosen word following `state`.
        """
        candidates, weights = zip(*self.state_map[state].items())
        return random.choices(candidates, weights)[0]

    def sentence_gen(self, start: ChainState = None) -> Generator[str]:
        """Successively yield words from a random walk on the chain.

        Starting from an initial state, the generator will yield words from the
        chain until a `SENTENCE_END` state is reached.

        Parameters
        ----------
        start : ChainState, optional
            The chain state to begin at. If unspecified, the chain will start
            at the `SENTENCE_BEGIN` state.

        Yields
        ------
        str
            A randomly selected word from the chain.
        """
        if start is None:
            start = [self.SENTENCE_BEGIN] * self._order
        elif len(start) != self._order:
            raise TypeError(
                f"start sequence length must match the chain's order ({self._order})")
        else:
            yield from filter(lambda x: x is not self.SENTENCE_BEGIN, start)
        sequence = deque(start, maxlen=self._order)
        while True:
            word = self.transition(tuple(sequence))
            if word == self.SENTENCE_END:
                break
            yield word
            sequence.append(word)

    # TODO: similarity_threshold
    # TODO: starts_with parameter; ensure sentence begins with the given
    # string. mutually exclusive with start
    def make_sentence(self, attempts: int = 20, start: ChainState = None, *,
                      min_words: int = 1, max_words: int = None,
                      strict_quotes: bool = True,
                      similarity_threshold: float = 0.6) -> Optional[str]:
        """Attempt to generate a sentence with variable quality control.

        This method will repeated generate sentences until one is generated
        that meets all expected criteria. It acts as a configurable
        quality-control filter that tries to ensure that only interesting
        sentences are generated.

        Parameters
        ----------
        attempts : int, optional
            Maximum number of tries to generate a conformant sentence before
            giving up. and returning `None`. If `attempts` is `None`, sentences
            will be endlessly generated until a valid one is generated.
            Defaults to 20.
        start : ChainState, optional
            The chain state to begin with. Same as for `gen_sentence`.
        min_words : int, optional
            The generated sentence must have at least this many words. Defaults
            to 1.
        max_words : int, optional
            The generated sentence cannot have more than this many words. If
            `max_words` is `None` (the default), the max length is
            unrestricted.
        strict_quotes : bool, optional
            If `True` (the default), then sentences with quotation marks
            (``"``) must be properly closed to be considered valid.
        similarity_threshold : float, optional
            A ratio from 0.0 to 1.0 that determines how similar a generated
            sentence can be to a sentence in the `corpus` to be considered
            valid. If the generated words overlap a sentence in the `corpus` by
            the given ratio, the generated sentence is discarded. Defaults to
            0.6.

        Returns
        -------
        Optional[str]
            A sentence meeting all criteria, or `None` if one could not be
            generated within the specified number of attempts.
        """
        if min_words < 0:
            raise ValueError('min_words cannot be negative')
        if max_words is not None and max_words < 0:
            raise ValueError('max_words cannot be negative')
        limit = repeat(True) if attempts is None else range(attempts)
        close_quote_pat = re.compile(r'"[.!?]*$')
        for _ in limit:
            tokens = []
            quote_stack = []
            for token in self.sentence_gen(start):
                if strict_quotes:
                    if token == '"' or '"' in token[1:-1]:
                        continue
                    if token[0] == '"':
                        quote_stack.append('o')  # open quote
                    if close_quote_pat.search(token):
                        quote_stack.append('c')  # closing quote
                tokens.append(token)
            word_count = len(tokens)
            if (word_count < min_words
                    or max_words is not None and word_count > max_words):
                continue
            if strict_quotes and quote_stack:
                if quote_stack[0] == 'c' or len(quote_stack) % 2 != 0:
                    continue  # At least one quote is missing
                if not all(a != b for a, b in zip(*[iter(quote_stack)] * 2)):
                    continue  # Mismatched open/close quotes
            if sentence := self.format_sentence(tokens):
                return sentence
        return None


class Tokenizer:
    """Customizable string tokenizer."""

    COMMON_URI_SCHEMES = re.compile(
        r'[jo]dbc|[st]?ftp|about|bitcoin|bzr|chrome-?|cvs|dav|dns|doi|file|geo'
        r'|git|http|imap|irc|ldap|magnet|mailto|nfs|rsync|rt(mf?|s)p|s3|sip'
        r'|skype|slack|smb|sms|spotify|ssh|steam|stun|svn|vnc|xmpp'
    )

    def __init__(self, *,
                 reject_patterns: list[str] = None,
                 accept_patterns: list[str] = None,
                 filter_patterns: list[str] = None,
                 word_split_pat: str = r'\s+'):

        def init_patterns(patterns):
            if patterns is None:
                return []
            return [re.compile(pat) for pat in patterns]

        self.reject_patterns = init_patterns(reject_patterns)
        self.accept_patterns = init_patterns(accept_patterns)
        self.filter_patterns = init_patterns(filter_patterns)
        self.word_split_pat = re.compile(word_split_pat)

    def tokenize(self, line: str) -> list[str]:
        """Split a string into valid tokens.

        Which tokens are considered "valid" is dependent upon how the
        `Tokenizer` is configured.
        """
        tokens = []
        accept = any(pat.search(line) for pat in self.accept_patterns)
        reject = any(pat.search(line) for pat in self.reject_patterns)
        if accept or not reject:
            for word in filter(bool, self.word_split_pat.split(line)):
                if any(pat.search(word) for pat in self.accept_patterns):
                    valid = True
                else:
                    valid = (
                        not self.is_probably_uri(word)
                        and not any(pat.search(word) for pat in self.filter_patterns)
                    )
                if not valid:
                    continue
                tokens.append(word)
        return tokens

    # TODO: handle markdown links, e.g. [foo](https://example.com)
    def is_probably_uri(self, token: str) -> bool:
        """Check if the given token is probably a URI."""
        if ':' in token and not token.endswith(':'):
            maybe_uri = urlparse(token)
            if maybe_uri.scheme and maybe_uri.scheme[0].isdecimal():
                # urllib isn't strict about this...
                return False
            return (
                self.COMMON_URI_SCHEMES.match(maybe_uri.scheme)
                or maybe_uri.netloc
                # 2-char schemes are rare or otherwise obscure
                or len(maybe_uri.scheme) > 2 and maybe_uri.path
            )
        return False


def update_chain_dump(chain: MarkovSentenceGenerator = None) -> Optional[Path]:
    """Serialize the current state of the Markov chain to disk, if enabled."""
    if chain is None:
        chain = CHAIN
    path = CFG.get('DumpPath', DEFAULT_DUMP_PATH)
    if CFG.get('SaveToDisk', False):
        if compress := CFG.get('CompressSave', True):
            path = path.with_suffix('.pickle.gz')
            open_func = gzip.open
        else:
            open_func = open
        logger.debug(
            f"Dumping {'un' if not compress else ''}compressed chain to {path}")
        with open_func(path, 'wb') as dumpfile:
            chain.dump(dumpfile)
        return path
    return None


async def database_corpus_count() -> int:
    """Return the number of lines in the database corpus."""
    async with DB.cursor() as cur:
        await cur.execute('SELECT count(*) FROM markov_corpus')
        return (await cur.fetchone())[0]


async def database_get_corpus() -> AsyncGenerator[list[str]]:
    """Yield lines from the database corpus.

    Each yielded line consists of a list of words, conveniently assignable to
    a chain corpus.
    """
    async with DB.cursor() as cur:
        await cur.execute('SELECT line FROM markov_corpus')
        for line in (row['line'] for row in await cur.fetchall()):
            yield line.split()


async def module_register(core):
    """Initialize mdoule."""
    global CORE, CFG, DB, get_participant, get_source, CHAIN, TOKENIZERS, DEFAULT_DUMP_PATH
    CORE = core
    DEFAULT_DUMP_PATH = CORE.data_dir / 'markov.pickle'

    DB = await core.database_connect(MOD_ID)
    await _init_database()
    get_participant = partial(getpart, DB)
    get_source = partial(getsrc, DB)

    # TEMP: TODO: decide between monolithic modules.toml or per-feature config
    CFG = core.load_config('modules')[MODULE_NAME]

    TOKENIZERS = _init_tokenizers()
    CHAIN = await _init_chain()

    await _register_commands()


async def module_unregister():
    """Prepare for shutdown."""
    await CORE.database_disconnect(MOD_ID)


async def module_on_config_reloaded(ctx, name):
    """Handle `Core` config reload event."""
    if name == 'ZeroBot':
        _init_tokenizers()
        _init_chain()


async def module_on_config_changed(ctx, name, key, old, new):
    """Handle `Core` config change event."""
    try:
        root, subkey = key.split('.', maxsplit=1)
    except IndexError:
        root, subkey = key, None
    if name == 'ZeroBot' and key == 'Core.CmdPrefix':
        _init_tokenizers()
    elif name == 'modules' and root == 'Markov':
        if subkey == 'Order':
            CHAIN.order = new
            update_chain_dump()


# TODO: also add patterns from config
def _init_tokenizers():
    """Set up protocol tokenizers."""
    tokenizers = {
        '_default_': Tokenizer(
            reject_patterns=[f'^{CORE.cmdprefix}\\w+']
        ),
        'discord': Tokenizer(
            reject_patterns=[r'\|\|.*\|\|', f'^{CORE.cmdprefix}\\w+',
                             r'^(?:@\S+\s*)+$'],
            filter_patterns=[r'<a?:\w+:\d+>', r'<(@[!&]?|#)\d+>'],
        )
    }
    return tokenizers


async def _init_chain():
    """Set up Markov chain."""
    from_scratch, tried_load = True, False
    chain_dump = CFG.get('DumpPath', DEFAULT_DUMP_PATH)
    if CFG.get('CompressSave', True):
        chain_dump.unlink(missing_ok=True)
        chain_dump = chain_dump.with_suffix('.pickle.gz')
        open_func = gzip.open
    else:
        chain_dump.with_suffix('.pickle.gz').unlink(missing_ok=True)
        open_func = open

    if chain_dump.exists():
        logger.info('Found chain dump file; loading from disk')
        try:
            with open_func(chain_dump, 'rb') as dumpfile:
                chain = MarkovSentenceGenerator.from_dump(dumpfile)
            if len(chain.corpus) != await database_corpus_count():
                logger.info('Chain corpus out of date, pulling from database')
                chain.corpus = [line async for line in database_get_corpus()]
                chain.rebuild()
                update_chain_dump(chain)
        except (OSError, pickle.UnpicklingError) as ex:
            logger.error(f'Failed to load chain dump file: {ex}')
        else:
            from_scratch = False
        finally:
            tried_load = True
    if from_scratch:
        if not tried_load:
            logger.info('No chain dump file found')
        logger.info('Building chain from scratch')
        corpus = [line async for line in database_get_corpus()]
        chain = MarkovSentenceGenerator(corpus, CFG.get('Order'))
        update_chain_dump(chain)
    return chain


async def _init_database():
    """Initialize database tables."""
    await DB.executescript("""
        CREATE TABLE IF NOT EXISTS "markov_corpus" (
            "line_id"   INTEGER NOT NULL,
            "line"      TEXT NOT NULL,
            "source"    INTEGER,
            "author"    INTEGER,
            "timestamp" DATETIME DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY ("line_id"),
            FOREIGN KEY ("source") REFERENCES "sources" ("source_id")
                ON UPDATE CASCADE
                ON DELETE SET NULL,
            FOREIGN KEY ("author") REFERENCES "participants" ("participant_id")
                ON UPDATE CASCADE
                ON DELETE SET NULL
        );
    """)


async def _register_commands():
    """Register our commands."""
    cmds = []
    cmd_markov = CommandParser(
        'markov', "Manage ZeroBot's Markov chain sentence generator.")
    add_subcmd = cmd_markov.make_adder(metavar='OPERATION', dest='subcmd',
                                       required=False)

    # TODO: allow specifying a source
    subcmd_learn = add_subcmd('learn', 'Query or adjust learning settings')
    subcmd_learn.add_argument(
        'state', nargs='?', choices=['on', 'off'], type=lambda x: x.lower(),
        help='Toggle learning on or off, or show the current state.')

    subcmd_info = add_subcmd('info', 'Show information about the Markov chain')
    subcmd_dump = add_subcmd(
        'dump', 'Save the state of the Markov chain to disk.')
    cmds.append(cmd_markov)

    cmd_talk = CommandParser(
        'talk', "Make ZeroBot say what's on his mind; generates a sentence from the Markov chain.")
    cmds.append(cmd_talk)

    CORE.command_register(MOD_ID, *cmds)


async def module_on_message(ctx, message):
    """Handle `Core` message event."""
    if not CFG.get('Learning.Enabled', False) or ctx.user == message.source:
        return
    # TODO: Proper protocol-agnostic 'DirectMessage' class
    if hasattr(message.destination, 'recipient'):
        # For privacy reasons, don't learn from direct messages
        return
    if message.channel.name in CFG.get('Learning.Blacklist', []):
        return
    if not (body := message.clean_content.strip()):
        return
    async with DB.cursor() as cur:
        for line in body.split('\n'):
            tokens = TOKENIZERS.get(
                ctx.protocol, TOKENIZERS['_default_']).tokenize(line)
            if len(tokens) < 2:
                continue
            date = message.created_at.replace(microsecond=0)
            author = await get_participant(message.author.name)
            source = await get_source(
                ctx.protocol, message.server.name, message.channel.name)
            await cur.execute("""
                INSERT INTO markov_corpus (line, source, author, timestamp)
                VALUES (?, ?, ?, ?)
            """, (' '.join(tokens), source.id, author.id, date))
            # TODO: hot insert line into chain
    await DB.commit()


async def module_command_markov(ctx, parsed):
    """Handle `markov` command."""
    subcmd = parsed.subcmd
    if subcmd == 'learn':
        if parsed.args['state'] is not None:
            state = parsed.args['state'] == 'on'
            CFG['Learning.Enabled'] = state
            if state:
                response = 'Okay, now learning how to speak!'
            else:
                response = 'Gotcha, no longer paying attention.'
        else:
            if CFG['Learning.Enabled']:
                response = 'I am currently learning.'
            else:
                response = "I'm not paying attention at the moment."
    elif subcmd == 'info':
        lines, words = 0, 0
        for line in CHAIN.corpus:
            lines += 1
            words += len(line)
        learning = '' if CFG.get('Learning.Enabled', False) else ' not'
        response = (
            f"My chain's corpus currently holds {lines:,} lines consisting of "
            f'{words:,} words, averaging {words / lines:,.3f} words per line. '
            f'I am{learning} currently learning new lines.'
        )
    elif subcmd == 'dump':
        if parsed.invoker != ctx.owner:
            await ctx.reply_command_result(
                parsed, f'Sorry, currently only {ctx.owner.name} can do that.')
            return
        path = update_chain_dump()
        size = path.stat().st_size / 1024 ** 2
        response = f'Dumped chain to {path} ({size:,.2f}MB)'

    await ctx.module_message(parsed.source, response)


async def module_command_talk(ctx, parsed):
    """Handle `talk` command."""
    sentence = CHAIN.make_sentence(
        attempts=CFG.get('Sentences.Attempts'),
        min_words=CFG.get('Sentences.MinWords'),
        max_words=CFG.get('Sentences.MaxWords'),
        strict_quotes=CFG.get('Sentences.StrictQuotes'),
        similarity_threshold=CFG.get('Sentences.SimilarityThreshold')
    )
    await ctx.module_message(parsed.source, sentence)
