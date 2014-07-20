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

    def __iter__(self):
        while True:
            yield self.recv()


def pipe(hub):
    sender = Sender(hub)
    recver = Recver(hub)

    sender.pair_to(recver)
    recver.pair_to(sender)

    return sender, recver


def stream(hub):
    def dec(f):
        sender, recver = pipe(hub)
        hub.spawn(f, sender)
        return recver
    return dec


def map(hub, upstream):
    def wrap(f):
        sender, recver = pipe(hub)
        @hub.spawn
        def _():
            for item in upstream:
                sender.send(f(item))
        return recver
    return wrap


def test_stream():
    h = vanilla.Hub()

    print
    print

    @stream(h)
    def counter(out):
        for i in xrange(10):
            print "s", i
            out.send(i)


    @map(h, counter)
    def mapped(n):
        return n * 2

    print mapped.recv()
    print mapped.recv()
    print mapped.recv()

    print
    print
