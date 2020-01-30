"""protocol/irc/server.py

Implementation of Server ABC for the IRC protocol.
"""

import ZeroBot.common.abc

class Server(abc.Server):
    """Represents a server on an IRC network.

    Attributes
    ----------
    hostname: str
        The hostname of server to connect to.
    port: int
        The port to connect on, defaults to 6667 (or 6697 for TLS connections).
    name: str
        User-defined friendly name for this server; may be any arbitrary name.
        If ``None``, will fall back to hostname.
    ipv6: bool
        Whether or not the connection uses IPv6.
    tls: bool
        Whether or not the connection is using TLS.
    password: Optional[str]
        The password required to connect to the server, or ``None`` if
        a password isn't required.
    servername: str
        The name returned by the server. This is typically the same as the
        hostname, however a server can report whatever name it wants, which may
        not match the hostname. Will be ``None`` until successful connection.
    """

    # TODO: Set servername on connection

    def __init__(self, hostname: str, port: int=None, *, name: str=None,
                 ipv6: bool=False, tls: bool=False, password: str=None):
        self.hostname = hostname
        if port is None:
            self.port = 6697 if tls else 6667
        else:
            self.port = port
        self.tls = tls
        self.password = password
        self.servername = None
        self.name = name if name is not None else self.hostname

    def __repr__(self):
        attrs = ['hostname', 'port', 'tls', 'password', 'name']
        return f"{self.__class__.__name__}({' '.join(f'{a}={getattr(self, a)}' for a in attrs)})"

    def __str__(self):
        return self.name if self.name is not None else self.hostname

    def __eq__(self, other):
        return ((self.hostname, self.port, self.tls) ==
                (other.hostname, other.port, other.tls))

    def connected(self) -> bool:
        """Whether or not the Server is currenlty connected."""
        raise NotImplementedError('TODO')

