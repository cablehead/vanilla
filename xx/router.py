import vanilla

from vanilla import *

import weakref
import gc

import pytest


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

    @property
    def other(self):
        return self.pair().current

    @property
    def ready(self):
        return self.other is not None

    def select(self, current=None):
        assert self.current is None
        self.current = current or getcurrent()

    def unselect(self):
        assert self.current == getcurrent()
        self.current = None

    def pause(self, timeout=-1):
        self.select()
        try:
            _, ret = self.hub.pause(timeout=timeout)
        finally:
            self.unselect()
        return ret


class Sender(Pair):
    def send(self, item, timeout=-1):
        if not self.ready:
            self.pause(timeout=timeout)
        return self.hub.switch_to(self.other, self.pair(), item)


class Recver(Pair):
    def recv(self, timeout=-1):
        # only allow one recv at a time
        assert self.current is None

        if self.ready:
            self.current = getcurrent()
            # switch directly, as we need to pause
            _, ret = self.other.switch(self.pair(), None)
            self.current = None
            return ret

        return self.pause(timeout=timeout)


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
        if pair.ready:
            return pair, isinstance(pair, Recver) and pair.recv() or None

    for pair in pairs:
        pair.select()

    fired, item = hub.pause()

    for pair in pairs:
        pair.unselect()

    return fired, item


def buffer(hub, size):
    buff = collections.deque()

    # TODO: don't form a closure around sender and recver
    sender, _recver = pipe(hub)
    _sender, recver = pipe(hub)

    @hub.spawn
    def _():
        while True:
            watch = []
            if len(buff) < size:
                watch.append(_recver)
            if buff:
                watch.append(_sender)

            ch, item = select(hub, *watch)

            if ch == _recver:
                buff.append(item)

            elif ch == _sender:
                item = buff.popleft()
                _sender.send(item)

    return sender, recver


def test_stream():
    h = vanilla.Hub()

    @stream(h)
    def counter(sender):
        for i in xrange(10):
            sender.send(i)

    assert counter.recv() == 0
    h.sleep(10)
    assert counter.recv() == 1


def test_select():
    h = vanilla.Hub()

    s1, r1 = pipe(h)
    s2, r2 = pipe(h)
    check_s, check_r = pipe(h)

    @h.spawn
    def _():
        check_s.send(r1.recv())

    @h.spawn
    def _():
        s2.send(10)
        check_s.send('done')

    ch, item = select(h, s1, r2)
    assert ch == s1
    s1.send(20)

    ch, item = select(h, s1, r2)
    assert ch == r2
    assert item == 10

    assert check_r.recv() == 20
    assert check_r.recv() == 'done'


def test_timeout():
    h = vanilla.Hub()

    sender, recver = pipe(h)
    check_sender, check_recver = pipe(h)

    pytest.raises(vanilla.Timeout, sender.send, 12, timeout=0)
    pytest.raises(vanilla.Timeout, recver.recv, timeout=0)
    pytest.raises(vanilla.Timeout, sender.send, 12, timeout=0)

    @h.spawn
    def _():
        h.sleep(20)
        check_sender.send(recver.recv())

    pytest.raises(vanilla.Timeout, sender.send, 12, timeout=10)
    sender.send(12, timeout=20)
    assert check_recver.recv() == 12

    @h.spawn
    def _():
        h.sleep(20)
        sender.send(12)

    pytest.raises(vanilla.Timeout, recver.recv, timeout=10)
    assert recver.recv(timeout=20) == 12


def test_buffer():
    h = vanilla.Hub()

    sender, recver = buffer(h, 2)

    sender.send(1)
    sender.send(2)

    assert recver.recv() == 1
    assert recver.recv() == 2

