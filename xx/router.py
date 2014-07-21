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

    def ready(self):
        return self.pair().current is not None

    def select(self):
        assert self.current is None
        self.current = getcurrent()

    def unselect(self):
        assert self.current == getcurrent()
        self.current = None

    def pause(self):
        self.select()
        ret = self.hub.pause()
        self.unselect()
        return ret


class Sender(Pair):
    def send(self, item):
        if self.ready():
            current = self.pair().current
        else:
            current = self.pause()

        self.hub.switch_to(current, item)


class Recver(Pair):
    def recv(self):
        if self.ready():
            item = self.hub.switch_to(self.pair().current, getcurrent())
            return item
        return self.pause()


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


def pulse(hub, ms, item=True):
    @stream(hub)
    def _(out):
        while True:
            hub.sleep(ms)
            out.send(item)
    return _


def select(hub, *pairs):
    for pair in pairs:
        if pair.ready():
            return pair.recv()

    for pair in pairs:
        pair.select()

    item = hub.pause()

    for pair in pairs:
        pair.unselect()

    return item


def test_stream():
    print
    print

    h = vanilla.Hub()

    ch1 = pulse(h, 1000, 'boom')
    h.sleep(500)
    ch2 = pulse(h, 1000, 'tick')

    while True:
        print select(h, ch1, ch2)
