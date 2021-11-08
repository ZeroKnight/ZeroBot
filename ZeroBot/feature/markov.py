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
import zlib
from collections import deque
from functools import partial
from io import StringIO
from itertools import repeat
from pathlib import Path
from typing import (AsyncGenerator, Any, Dict, Generator, List, Optional,
                    Tuple, Union)
from urllib.parse import urlparse

from ZeroBot.common import CommandParser
from ZeroBot.common.enums import CmdErrorType
from ZeroBot.database import get_participant as getpart
from ZeroBot.database import find_participant as findpart
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
find_participant = None
get_source = None

logger = logging.getLogger('ZeroBot.Feature.Markov')

CHAIN = None
TOKENIZERS = None
DEFAULT_DUMP_PATH = None
DEFAULT_ORDER = 2
DEFAULT_SIMILARITY_THRESHOLD = 0.6
FOCUSED_CHAINS = {}


# TODO: if a markov request was generated naturally (asking zerobot what's on
# his mind, he chooses to at random, etc.) and we're on discord, send
# a "typing" event and wait for 1.0-3.0 seconds before sending

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
    Candidates = Dict[Token, int]
    ChainModel = Dict[ChainState, Candidates]

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

    def _add_tokens_to_model(self, tokens: list[Token], model: ChainModel):
        for i in range(len(tokens) - self._order):
            token_seq = tuple(tokens[i:i + self._order])
            next_token = tokens[i + self._order]
            try:
                edges = model.setdefault(token_seq, {})
                edges[next_token] += 1
            except KeyError:
                edges[next_token] = 1

    @staticmethod
    def _choose_next_word(candidates: Candidates) -> str:
        words, weights = zip(*candidates.items())
        return random.choices(words, weights)[0]

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
            self._add_tokens_to_model(tokens, state_map)
        return state_map

    def rebuild(self):
        """Rebuild the chain's state map from the current corpus."""
        self.state_map = self.build(self.corpus)

    def insert(self, tokens: list[Token]):
        """Add a line to the chain's corpus *and* the current model.

        Facilitates simple, incremental addition of input to the chain and does
        not require a complete rebuild of the chain model, which can be an
        expensive process.

        Parameters
        ----------
        tokens : list[Token]
            A list of tokens to add, typically the result of
            `Tokenizer.tokenize`.
        """
        self.corpus.append(tokens)
        self._add_tokens_to_model(tokens, self.state_map)

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
        return self._choose_next_word(self.state_map[state])

    def sentence_gen(self, start: ChainState = None) -> Generator[str]:
        """Successively yield words from a random walk on the chain.

        Starting from an initial state, the generator will yield words from the
        chain until a `SENTENCE_END` state is reached.

        Parameters
        ----------
        start : ChainState, optional
            The chain state to begin at. If unspecified, the chain will start
            at the `SENTENCE_BEGIN` state.

        Raises
        ------
        KeyError
            May raise `KeyError` depending on the chain order if the randomly
            chosen state is not in the chain.

        Yields
        ------
        str
            A randomly selected word from the chain.
        """
        word, prev_word = None, None
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

    def check_similarity(self, tokens: list[Token], threshold: float) -> bool:
        """Check if a token sequence is too similar to a line in the corpus.

        If the token sequence is too similar to an existing line in the corpus,
        this method returns `True`, otherwise the sequence is "unique enough"
        and returns `False`.

        Parameters
        ----------
        tokens : list[Tokens]
            The token sequence to check, usually one generated by the chain.
        threshold : float
            A number from 0.0 to 1.0 representing the upper limit of the
            percentage of tokens that must match an existing sequence to be
            considered too similar. A value of 1.0 necessitates an exact match
            to be considered too similar. A value of 0.0 is a no-op and will
            always return `False`.
        """
        # No-op for pointless threshold
        if threshold == 0.0:
            return False
        seq_len = round(len(tokens) * threshold)
        for i in range(len(tokens) - seq_len):
            sequence = tokens[i:i + seq_len]
            for line in self.corpus:
                word_count = len(line)
                if word_count < seq_len or (seq_len < word_count / seq_len):
                    # Ignore lines shorter than the sequence, and don't claim
                    # that comparatively tiny sequence lengths are similar to
                    # a long line.
                    continue
                # zip is helpful here as it only yields as far as the shortest
                # argument, which will only ever be our check sequence.
                if all(a == b for a, b in zip(sequence, line)):
                    return True
        return False

    def make_sentence(self, attempts: int = 20, start: ChainState = None, *,
                      min_words: int = 1, max_words: int = None,
                      starts_with: Union[str, list[str]]= None,
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
            giving up. and returning `None`. If `attempts` is 0, sentences will
            be endlessly generated until a valid one is generated.
            Defaults to 20.
        start : ChainState, optional
            The chain state to begin with. Same as for `gen_sentence`.
            Mutually exclusive with `starts_with`.
        starts_with : str or list of str, optional
            The generated sentence must begin with the specified sentence
            fragment. May either be a single string or a list of words.
            Mutually exlcusive with `start`.
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
            0.6. Set to `None` to disable this check.

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
        if starts_with is not None:
            if start is not None:
                raise ValueError(
                    "Parameters 'start' and 'starts_with' are mutually exclusive")
            if isinstance(starts_with, str):
                starts_with = starts_with.split(' ')
            if len(starts_with) < self.order:
                pad = (self.SENTENCE_BEGIN,) * (self.order - len(starts_with))
                start = pad + tuple(starts_with)
            else:
                start = tuple(starts_with[:self.order])
        limit = repeat(True) if attempts == 0 else range(attempts)
        close_quote_pat = re.compile(r'"[.!?]*$')
        for _ in limit:
            tokens = []
            quote_stack = []
            try:
                for token in self.sentence_gen(start):
                    if strict_quotes:
                        if token == '"' or '"' in token[1:-1]:
                            continue
                        if token[0] == '"':
                            quote_stack.append('o')  # open quote
                        if close_quote_pat.search(token):
                            quote_stack.append('c')  # closing quote
                    tokens.append(token)
            except KeyError as ex:
                logger.debug(f'Hit bad chain state: {ex}')
                continue
            word_count = len(tokens)
            if (word_count < min_words
                    or max_words is not None and word_count > max_words):
                continue
            if starts_with is not None and not all(a == b for a, b in zip(tokens, starts_with)):
                continue
            if strict_quotes and quote_stack:
                if quote_stack[0] == 'c' or len(quote_stack) % 2 != 0:
                    continue  # At least one quote is missing
                if not all(a != b for a, b in zip(*[iter(quote_stack)] * 2)):
                    continue  # Mismatched open/close quotes
            if (similarity_threshold
                    and self.check_similarity(tokens, similarity_threshold)):
                continue
            if sentence := self.format_sentence(tokens):
                return sentence
        return None

    def corpus_counts(self) -> tuple[int, int]:
        """Return the number of lines and total words in the corpus."""
        lines, words = 0, 0
        for line in self.corpus:
            lines += 1
            words += len(line)
        return lines, words


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


async def database_get_corpus(criteria: tuple[str, Any] = None) -> AsyncGenerator[list[str]]:
    """Yield lines from the database corpus.

    Each yielded line consists of a list of words, conveniently assignable to
    a chain corpus.
    """
    async with DB.cursor() as cur:
        if criteria is not None:
            await cur.execute(f"""
                SELECT line FROM markov_corpus
                WHERE {criteria[0]} = ?
            """, (criteria[1],))
        else:
            await cur.execute('SELECT line FROM markov_corpus')
        for line in (row['line'] for row in await cur.fetchall()):
            yield line.split()


async def module_register(core):
    """Initialize mdoule."""
    global CORE, CFG, DB, get_participant, find_participant, get_source, CHAIN, TOKENIZERS, DEFAULT_DUMP_PATH
    CORE = core
    DEFAULT_DUMP_PATH = CORE.data_dir / 'markov.pickle'

    DB = await core.database_connect(MOD_ID)
    await _init_database()
    get_participant = partial(getpart, DB)
    find_participant = partial(findpart, DB)
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
            await CORE.run_async(update_chain_dump)


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
                await CORE.run_async(chain.rebuild)
                await CORE.run_async(update_chain_dump, chain)
        except (OSError, EOFError, zlib.error, pickle.UnpicklingError) as ex:
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
        chain = MarkovSentenceGenerator(corpus, CFG.get('Order', DEFAULT_ORDER))
        await CORE.run_async(update_chain_dump, chain)
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

    subcmd_learn = add_subcmd('learn', 'Query or adjust learning settings')
    subcmd_learn.add_argument(
        'state', nargs='?', choices=['on', 'off'], type=lambda x: x.lower(),
        help='Toggle learning on or off, or show the current state.')

    subcmd_info = add_subcmd('info', 'Show information about the Markov chain')
    subcmd_rebuild = add_subcmd(
        'rebuild', 'Force a rebuild of the Markov chain from the database corpus')
    subcmd_dump = add_subcmd(
        'dump', 'Save the state of the Markov chain to disk.')
    cmds.append(cmd_markov)

    cmd_talk = CommandParser(
        'talk', "Make ZeroBot say what's on his mind; generates a sentence from the Markov chain.")
    cmd_talk.add_argument(
        '-s', '--starts-with', nargs='+', metavar='word',
        help='Make the generated sentence start with the given value.')
    cmd_talk.add_argument(
        '-f', '--focus', metavar='target',
        help='Only use data from a specific user/channel to generate sentences')
    cmds.append(cmd_talk)

    CORE.command_register(MOD_ID, *cmds)


def can_learn(ctx, message) -> bool:
    """Check if ZeroBot can learn from the given message."""
    if (
        ctx.user == message.source
        or not CFG.get('Learning.Enabled', False)
        # TODO: Proper protocol-agnostic 'DirectMessage' class
        # For privacy reasons, don't learn from direct messages
        or hasattr(message.destination, 'recipient')
        or message.channel.name in CFG.get('Learning.Blacklist', [])
    ):
        return False
    return True


async def module_on_message(ctx, message):
    """Handle `Core` message event."""
    body = message.clean_content.strip()
    if not (can_learn(ctx, message) and body):
        return
    async with DB.cursor() as cur:
        for line in body.split('\n'):
            tokens = TOKENIZERS.get(
                ctx.protocol, TOKENIZERS['_default_']).tokenize(line)
            if len(tokens) < CFG.get('Order', DEFAULT_ORDER):
                continue
            date = message.created_at
            author = await get_participant(message.author.name)
            source = await get_source(
                ctx.protocol, message.server.name, message.channel.name)
            await cur.execute("""
                INSERT INTO markov_corpus (line, source, author, timestamp)
                VALUES (?, ?, ?, ?)
            """, (' '.join(tokens), source.id, author.id, date))
            CHAIN.insert(tokens)
    await DB.commit()


async def module_command_markov(ctx, parsed):
    """Handle `markov` command."""
    subcmd = parsed.subcmd
    if subcmd == 'learn':
        if parsed.args['state'] is not None:
            if parsed.invoker != ctx.owner:
                await ctx.reply_command_result(
                    parsed, f'Sorry, currently only {ctx.owner.name} can do that.')
                return
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
        lines, words = await CORE.run_async(CHAIN.corpus_counts)
        learning = '' if CFG.get('Learning.Enabled', False) else ' not'
        response = (
            f"My chain's corpus currently holds {lines:,} lines consisting of "
            f'{words:,} words, averaging {words / lines:,.3f} words per line. '
            f'I am{learning} currently learning new lines.'
        )
    elif subcmd == 'rebuild':
        if parsed.invoker != ctx.owner:
            await ctx.reply_command_result(
                parsed, f'Sorry, currently only {ctx.owner.name} can do that.')
            return
        before = await CORE.run_async(CHAIN.corpus_counts)
        await CORE.run_async(CHAIN.rebuild)
        after = await CORE.run_async(CHAIN.corpus_counts)
        response = f'Chain rebuilt with a line delta of {after[0] - before[0]:+,}'
    elif subcmd == 'dump':
        if parsed.invoker != ctx.owner:
            await ctx.reply_command_result(
                parsed, f'Sorry, currently only {ctx.owner.name} can do that.')
            return
        path = await CORE.run_async(update_chain_dump)
        size = path.stat().st_size / 1024 ** 2
        response = f'Dumped chain to {path} ({size:,.2f}MB)'

    await ctx.module_message(parsed.source, response)


async def make_focused_chain(target: str) -> MarkovSentenceGenerator:
    if target[0] == '#':
        raise NotImplementedError('Not yet implemented')
    else:
        corpus_src = await find_participant(target)
    if corpus_src is None:
        raise ValueError('Bad target')
    corpus = [line async for line in database_get_corpus(('author', corpus_src.id))]
    return MarkovSentenceGenerator(
        corpus=corpus, order=CFG.get('Order', DEFAULT_ORDER))


async def module_command_talk(ctx, parsed):
    """Handle `talk` command."""
    attempts = CFG.get('Sentences.Attempts', 0)
    sw_attempts = CFG.get('Sentences.StartsWithAttempts', 10000)

    focus = parsed.args['focus']
    if focus is not None:
        try:
            # TODO: limit number of cached chains
            chain = FOCUSED_CHAINS[focus]
        except KeyError:
            try:
                chain = await make_focused_chain(focus)
                FOCUSED_CHAINS[focus] = chain
            except ValueError:
                await CORE.module_send_event(
                    'invalid_command', ctx, parsed.msg, CmdErrorType.NotFound)
                return
            except NotImplementedError as ex:
                await ctx.reply_command_result(parsed, ex.msg)
                return
    else:
        chain = CHAIN

    # Enforce an attempt limit when starts_with is given to avoid trying to
    # generate an impossible sentence
    if parsed.args['starts_with']:
        attempts = min(max(attempts, sw_attempts + 1), sw_attempts)

    sentence = chain.make_sentence(
        attempts=attempts,
        min_words=CFG.get('Sentences.MinWords'),
        max_words=CFG.get('Sentences.MaxWords'),
        strict_quotes=CFG.get('Sentences.StrictQuotes'),
        starts_with=parsed.args['starts_with'],
        similarity_threshold=CFG.get(
            'Sentences.SimilarityThreshold', DEFAULT_SIMILARITY_THRESHOLD)
    )
    if sentence is None:
        idk_response = random.choice((
            "Yeah, I've got nothing for that one...",
            'I no can word that good yet...',
            "I literally can't even",
            'I hurt my head trying to think of something for that...'))
        await ctx.module_message(
            parsed.source, f'{parsed.invoker.mention} {idk_response}')
    else:
        await ctx.module_message(parsed.source, sentence)
