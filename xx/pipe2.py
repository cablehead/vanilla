import vanilla

from vanilla import *

import weakref
import gc


class Pair(object):
    __slots__ = ['hub', 'current', 'pair']

    def __init__(self, hub):
        self.hub = hub
        self.current = None
        self.pair = None

    def yack(self, *a, **kw):
        print "YAKCK UAKC", a, kw, self.__class__

    def pair_to(self, pair):
        self.pair = weakref.ref(pair, self.yack)


class Sender(Pair):
    def send(self, item):
        if self.pair().current:
            current = self.pair().current

        else:
            self.current = getcurrent()
            current = self.hub.pause()
            self.current = None

        self.hub.switch_to(current, item)


class Recver(Pair):
    def recv(self):
        if self.pair().current:
            return self.hub.switch_to(self.pair().current, getcurrent())

        self.current = getcurrent()
        item = self.hub.pause()
        self.current = None
        return item


class Pipe(object):
    __slots__ = ['hub', 'sender', 'recver']

    def __init__(self, hub):
        self.hub = hub

        self.sender = Sender(hub)
        self.recver = Recver(hub)

        self.sender.pair_to(self.recver)
        self.recver.pair_to(self.sender)

    def send(self, item):
        self.sender.send(item)

    def recv(self):
        return self.recver.recv()


def test_pipe():
    h = vanilla.Hub()

    pipe = Pipe(h)
    @h.spawn
    def _():
        for i in xrange(10):
            print "s", i
            pipe.send(i)

    print
    print
    print "-----"
    print pipe.recv()
    print
    h.sleep(10)
    print "a"
    print pipe.recv()
    print "b"

    del pipe.recver
