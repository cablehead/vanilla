import functools
import socket
import errno
import os

import vanilla.message
import vanilla.poll


class __plugin__(object):
    def __init__(self, hub):
        self.hub = hub

    def create(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setblocking(0)
        return Sock(self.hub, sock)

    def listen(self, port=0, host='127.0.0.1'):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((host, port))
        sock.setblocking(0)
        server = Sock(self.hub, sock)
        server.port = sock.getsockname()[1]
        return server


def Sock(hub, sock):
    sender = Sender(hub, sock)
    recver = Recver(hub, sock)
    return vanilla.message.Pair(sender, recver)


def Sender(hub, sock):
    sender, recver = hub.pipe()
    recver.consume(lambda a: sock.sendto(*a))
    return sender


def close(hub, fileno):
    try:
        os.close(fileno)
    except OSError:
        pass
    hub.unregister(fileno)


def Recver(hub, sock):
    sender, recver = hub.pipe()

    recver.onclose(functools.partial(close, hub, sock.fileno()))

    @hub.spawn
    def _():
        ready = hub.register(sock.fileno(), vanilla.poll.POLLIN)
        for _ in ready:
            while True:
                try:
                    got = sock.recvfrom(65507)
                except (socket.error, OSError), e:
                    if e.errno == errno.EAGAIN:
                        break
                    sender.close()
                    return
                sender.send(got)
        sender.close()

    return recver
