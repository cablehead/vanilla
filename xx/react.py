import vanilla

from vanilla import *

import weakref
import gc


class Pair(object):
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
        # only allow one recv at a time
        assert self.current is None

        if self.pair().current:
            return self.hub.switch_to(self.pair().current, getcurrent())

        self.current = getcurrent()
        item = self.hub.pause()
        self.current = None
        return item

    def __iter__(self):
        while True:
            yield self.recv()

    def pipe(self):
        sender, recver = pipe(self.hub)
        @self.hub.spawn
        def _():
            for item in self:
                sender.send(item)
        return recver

    def map(self, f):
        sender, recver = pipe(self.hub)
        @self.hub.spawn
        def _():
            for item in self:
                sender.send(f(item))
        return recver


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


def test_stream():
    h = vanilla.Hub()

    print
    print

    @stream(h)
    def counter(out):
        for i in xrange(10):
            print "s", i
            out.send(i)


    """
    @counter.map
    def double(n):
        return n * 2


    print double.recv()
    print double.recv()
    print double.recv()
    """

    ch = counter.pipe()
    print ch.recv()
    print ch.recv()



    print
    print
