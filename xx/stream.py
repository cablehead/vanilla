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

    @stream(h)
    def counter(out):
        for i in xrange(10):
            print "s", i
            out.send(i)

    print
    print
    print "-----"
    print counter.recv()
    print
    h.sleep(10)
    print "a"
    print counter.recv()
    print "b"

    del counter
    gc.collect()
