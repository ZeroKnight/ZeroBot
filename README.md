ZeroBot
=======

My eccentric, long-running, personal bot project
------------------------------------------------

ZeroBot is a modular, mutli-protocol (originally and primarily IRC) bot. This
bot exists primarily for amusement and arbitrary utility, but otherwise serves
no major or specific purpose. I created him to bum around in channels and
servers that I frequent, so he was originally and always will be a pet project.

Development Status
------------------

ZeroBot is currently being rewritten (again) in Python, and as such will not
have any of the [previous incarnation](https://github.com/ZeroKnight/ZeroBot-Perl)'s
functionality for a little bit.

Inconsequential Lore 📘
----------------------

Here be ramblings about ZeroBot's lifetime. They're not really for anyone in
particular aside from myself and a couple friends. You can safely ingore this
section; I won't be offended. 😛

### Genesis

This bot was my very first expedition into programming and I have always had
a particular fascination and fondness for IRC, so this goofy little bot holds
fluffy sentimental meaning to me. The reason for creating ZeroBot in the first
place was to learn programming and how the IRC protocol worked.

ZeroBot first came to life back in December 2011, and has undergone many
rewrites over the years, in multiple languages. In fact, this is something like
the fifth or sixth time I've rewritten him, whether in part or entirely!

I originally wrote ZeroBot in Python, inspired by **redroid**: the personal bot
of [Red Eclipse](https://www.redeclipse.net)'s lead developer, Quinton Reeves.
In this genesis, I had clumsily implemented bits of the IRC protocol on an
as-needed basis and added simple functionality like responding to chat in
absurd ways, small utility functions, and a database to collect humorous,
inspiring, or ridiculous-when-out-of-context quotes. He brought much amusement
to myself and our tiny IRC channel.

### First (attempted) Rewrite

However, over time I grew to dislike Python, and as a result gradually neglect
and eventually abandon and disconnect my poor bot for some time. In time,
I began to yearn for the deranged antics of my bot and decided to undertake the
first of many rewrites to come. I had initially started in C++, as I had always
been fond of the language and was my gateway into the programming world. Not far
into the rewrite I began to realize that I was still very inexperienced with
C++, and things were going very slowly and looking particularly awful, so I gave
up that incarnation not long after starting, and it currently remains buried
on a drive somewhere.

### The Perl Years

At around the same time I gave up on the C++ rewrite, I had decided that
I wanted to learn Perl, so I did what would end up becoming a personal trend
when learning a language: write (or rewrite in this case) an IRC bot! The Perl
incarnation of ZeroBot would end up being the furthest I had gotten with the
bot's design to this point, even going as far as performing not one, not two,
but **three** separate redesigns and reimplementations before arriving at his
current modular design over a few years. There were transitions between Moose
and Moo and back again, multiple configuration libraries, structural designs,
and an eternal struggle of attempting to whip PoCo::IRC and PoCo::Syndicator
into the shape I desired.

There were several periods of off-and-on development, as well as times where
ZeroBot was functional and times where he was non-functional. Despite this, his
latest design had finally begun to take shape, with the ability to dynamically
load and unload individual protocol and feature modules, along with
a hand-rolled command parser and templated logging system, and a bastardized
configuration system.

Despite this progress, long after switching from Moose to Moo, I began to run
into a bug with Moo, and began the annoying process of switching back to Moose.
I had been developing on Arch Linux, and each time Perl was updated, it meant
that all PerlX modules needed to be recompiled, which in my case were quite
a lot. Having never found a way to automate this tedious process correctly, as
well as having to deal with it for the hundredth time, I grew irritated and
disillusioned with Perl and its module ecosystem and began another period of
neglect that lasted 6 months at the time of this writing. Once again, my poor
bot would not see life for some time.

### Seduced by a Serpent: Harkening Back to Origins

Recently, I have fallen a bit in love with Python despite my fledgling opinions
from the past. Now armed with more experience and newer outlooks, I began to
appreciate and adore Python's *amazing* standard library and language features.
The nagging in the back of my head to continue working on my bot once again
resurfaced, but I dreaded going back to fighting my Perl development
environment, knowing it would need to be done again all over again in the
future. But with some wishful encouragement (read: demands) from my friends to
bring my damn bot back into working order and my newfound love for Python,
I made the decision to once again rewrite my lovable bot one last time.

This is where stand now: a return to origins; a return to glory. Since I have
already spent the time coming up with ZeroBot's current design, and the *many*
libraries and tools available in the Python ecosystem, I predict that I'll be
able to get back up to speed in much less time than the Perl version took, and
I will finally restore my beloved bot to his former glory and then some. I am
determined to bring this brain-damaged bastard back not just to IRC, but
Discord, Matrix, and any other protocol. That, and I *really* would like to not
have to manually archive new quotes by hand into an Evernote anymore. 😅

Long live ZeroBot!
