import gc

import pytest

import vanilla
import vanilla.message


# TODO: remove
import logging
logging.basicConfig()


@pytest.mark.parametrize('primitive, a', [
    ('pipe', ()),
    ('dealer', ()),
    ('router', ()),
    ('channel', ()), ])
class TestAbandoned(object):
    @staticmethod
    def assert_abandoned_sender(sender, check):
        pytest.raises(vanilla.Abandoned, sender.send, 10)
        check.send('done')

    def test_abandoned_sender_after_wait(self, primitive, a):
        h = vanilla.Hub()
        sender, recver = getattr(h, primitive)(*a)
        check = h.pipe()
        h.spawn(self.assert_abandoned_sender, sender, check)
        h.sleep(1)
        del recver
        gc.collect()
        assert check.recv() == 'done'

    def test_abandoned_sender_before_wait(self, primitive, a):
        h = vanilla.Hub()
        sender, recver = getattr(h, primitive)(*a)
        check = h.pipe()
        h.spawn(self.assert_abandoned_sender, sender, check)
        del recver
        gc.collect()
        assert check.recv() == 'done'

    @staticmethod
    def assert_abandoned_recver(recver, check):
        pytest.raises(vanilla.Abandoned, recver.recv)
        check.send('done')

    def test_abandoned_recver_after_wait(self, primitive, a):
        h = vanilla.Hub()
        sender, recver = getattr(h, primitive)(*a)
        check = h.pipe()
        h.spawn(self.assert_abandoned_recver, recver, check)
        h.sleep(1)
        del sender
        gc.collect()
        assert check.recv() == 'done'

    def test_abandoned_recver_before_wait(self, primitive, a):
        h = vanilla.Hub()
        sender, recver = getattr(h, primitive)(*a)
        check = h.pipe()
        h.spawn(self.assert_abandoned_recver, recver, check)
        del sender
        gc.collect()
        assert check.recv() == 'done'


class TestPipe(object):
    def test_deadlock(self):
        h = vanilla.Hub()
        p = h.pipe()
        pytest.raises(vanilla.Stop, p.send, 1)

    def test_close_recver(self):
        h = vanilla.Hub()

        check = h.pipe()
        sender, recver = h.pipe()

        @h.spawn
        def _():
            for i in xrange(10):
                try:
                    sender.send(i)
                except vanilla.Closed:
                    break
            check.send('done')

        assert recver.recv() == 0
        assert recver.recv() == 1
        recver.close()
        assert check.recv() == 'done'

    def test_close_sender(self):
        h = vanilla.Hub()

        check = h.pipe()
        sender, recver = h.pipe()

        @h.spawn
        def _():
            for i in recver:
                check.send(i)
            check.send('done')

        sender.send(0)
        assert check.recv() == 0
        sender.send(1)
        assert check.recv() == 1
        sender.close()
        assert check.recv() == 'done'

    def test_onclose(self):
        h = vanilla.Hub()
        p1 = h.pipe()
        p2 = h.queue(1)
        p1.onclose(p2.send, 'Toby')
        p1.close()
        assert p2.recv() == 'Toby'

    def test_onclose_piped_to_router(self):
        h = vanilla.Hub()
        sender, recver = h.pipe()

        p2 = h.queue(1)
        recver.onclose(p2.send, 'Toby')

        r = h.router()
        recver.pipe(r)
        r.close()

        assert p2.recv() == 'Toby'

    def test_timeout(self):
        h = vanilla.Hub()

        sender, recver = h.pipe()
        check = h.pipe()

        pytest.raises(vanilla.Timeout, sender.send, 12, timeout=0)
        pytest.raises(vanilla.Timeout, recver.recv, timeout=0)
        pytest.raises(vanilla.Timeout, sender.send, 12, timeout=0)

        @h.spawn
        def _():
            h.sleep(20)
            check.send(recver.recv())

        pytest.raises(vanilla.Timeout, sender.send, 12, timeout=10)
        sender.send(12, timeout=20)
        assert check.recv() == 12

        @h.spawn
        def _():
            h.sleep(20)
            sender.send(12)

        pytest.raises(vanilla.Timeout, recver.recv, timeout=10)
        assert recver.recv(timeout=20) == 12

    def test_throw_with_timeout(self):
        h = vanilla.Hub()
        sender, recver = h.pipe()
        h.spawn(sender.send, Exception())
        pytest.raises(Exception, recver.recv, timeout=20)
        assert h.scheduled.count == 0

    def test_select(self):
        h = vanilla.Hub()

        s1, r1 = h.pipe()
        s2, r2 = h.pipe()
        check = h.pipe()

        @h.spawn
        def _():
            check.send(r1.recv())

        @h.spawn
        def _():
            s2.send(10)
            check.send('done')

        ch, item = h.select([s1, r2])
        assert ch == s1
        s1.send(20)

        ch, item = h.select([s1, r2])
        assert ch == r2
        assert item == 10

        assert check.recv() == 20
        assert check.recv() == 'done'

    def test_select_timeout(self):
        h = vanilla.Hub()

        s1, r1 = h.pipe()
        s2, r2 = h.pipe()
        check = h.pipe()

        pytest.raises(vanilla.Timeout, h.select, [s1, r2], timeout=0)

        @h.spawn
        def _():
            h.sleep(20)
            check.send(r1.recv())

        pytest.raises(vanilla.Timeout, h.select, [s1, r2], timeout=10)

        ch, item = h.select([s1, r2], timeout=20)
        assert ch == s1
        s1.send(20)
        assert check.recv() == 20

        @h.spawn
        def _():
            h.sleep(20)
            s2.send(10)
            check.send('done')

        pytest.raises(vanilla.Timeout, h.select, [s1, r2], timeout=10)

        ch, item = h.select([s1, r2], timeout=20)
        assert ch == r2
        assert item == 10
        assert check.recv() == 'done'

    def test_pipe(self):
        h = vanilla.Hub()

        p1 = h.pipe()
        p2 = h.pipe()

        p1.pipe(p2)

        h.spawn(p1.send, 1)
        assert p2.recv() == 1

    def test_pipe_to_function(self):
        h = vanilla.Hub()

        p1 = h.pipe()

        @p1.pipe
        def p2(recver, sender):
            for item in recver:
                sender.send(item*2)

        h.spawn(p1.send, 1)
        assert p2.recv() == 2
        h.spawn(p1.send, 2)
        assert p2.recv() == 4

    def test_pipe_to_function_with_current_recver(self):
        h = vanilla.Hub()

        p1 = h.pipe()

        check = h.pipe()
        h.spawn(lambda: check.send(p1.recv()))
        h.sleep(1)

        p1 = p1.map(lambda x: x + 1)
        h.sleep(1)

        p1.send(1)
        assert check.recv() == 2

    def test_map(self):
        h = vanilla.Hub()
        p1 = h.pipe()
        p2 = p1.map(lambda x: x * 2)

        h.spawn(p1.send, 1)
        assert p2.recv() == 2

        h.spawn(p1.send, 2)
        assert p2.recv() == 4

    def test_map_raises(self):
        h = vanilla.Hub()

        class E(Exception):
            pass

        def f(x):
            raise E()

        p1 = h.pipe()
        p2 = p1.map(f)

        h.spawn(p1.send, 1)
        pytest.raises(E, p2.recv)

    def test_chain(self):
        h = vanilla.Hub()

        p = h.pipe()
        # s1, m1, r1
        # p is: s2, r1

        p = h.pipe().map(lambda x: x + 1).pipe(p)
        # s2, m3, f(r3, s3), m2, r2 --> s1, m1, r1
        # s2, m3, f(r3, s3), m2, r1
        # p is: s2, r1

        p = h.pipe().map(lambda x: x * 2).pipe(p)
        # s4, m5, f(r5, s5), m4, r4 --> s2, m3, f(r3, s3), m2, r1
        # s4, m5, f(r5, s5), m4, f(r3, s3), m2, r1
        # p is: s4, r1

        h.spawn(p.send, 2)
        h.sleep(1)

        assert p.recv() == 5

    def test_consume(self):
        h = vanilla.Hub()
        p = h.pipe()
        check = h.pipe()
        p.consume(lambda x: check.send(x))
        p.send(1)
        assert check.recv() == 1

    def test_exception(self):
        h = vanilla.Hub()

        p = h.pipe()
        check = h.pipe()

        @h.spawn
        def _():
            try:
                p.recv()
            except Exception, e:
                check.send(e.message)

        p.send(Exception('hai'))
        assert check.recv() == 'hai'

    # TODO: move to their own test suite
    def test_producer(self):
        h = vanilla.Hub()

        @h.producer
        def counter(sender):
            for i in xrange(10):
                sender.send(i)

        assert counter.recv() == 0
        h.sleep(10)
        assert counter.recv() == 1

    def test_trigger(self):
        h = vanilla.Hub()

        check = h.pipe()

        @h.trigger
        def go():
            check.send(1)

        h.sleep(1)
        gc.collect()

        go.trigger()
        assert check.recv() == 1

        pipe = go.middle

        h.sleep(1)
        del go
        gc.collect()
        h.sleep(1)
        gc.collect()
        h.sleep(1)

        assert pipe.recver() is None
        assert pipe.sender() is None


class TestQueue(object):
    def test_queue(self):
        h = vanilla.Hub()
        b = h.queue(2)

        b.send(1, timeout=0)
        b.send(2, timeout=0)
        pytest.raises(vanilla.Timeout, b.send, 3, timeout=0)
        assert b.recv() == 1

        b.send(3, timeout=0)
        assert b.recv() == 2
        assert b.recv() == 3

        gc.collect()
        h.sleep(1)

    def test_queue_close_sender(self):
        h = vanilla.Hub()
        sender, recver = h.queue(2)

        sender.send(1, timeout=0)
        sender.send(2, timeout=0)

        del sender
        gc.collect()

        assert recver.recv() == 1
        assert recver.recv() == 2

        gc.collect()
        h.sleep(1)


class TestPulse(object):
    def test_pulse(self):
        h = vanilla.Hub()

        trigger = h.pulse(20)
        pytest.raises(vanilla.Timeout, trigger.recv, timeout=0)

        h.sleep(20)
        assert trigger.recv(timeout=0)
        pytest.raises(vanilla.Timeout, trigger.recv, timeout=0)

        h.sleep(20)
        assert trigger.recv(timeout=0)
        pytest.raises(vanilla.Timeout, trigger.recv, timeout=0)

        h.stop()


class TestDealer(object):
    def test_send_then_recv(self):
        h = vanilla.Hub()
        d = h.dealer()
        h.spawn(d.send, 1)
        assert d.recv() == 1

    def test_recv_then_send(self):
        h = vanilla.Hub()

        d = h.dealer()
        q = h.queue(10)

        h.spawn(lambda: q.send(d.recv()))
        h.spawn(lambda: q.send(d.recv()))
        h.spawn(lambda: q.send(d.recv()))
        h.sleep(1)

        d.send(1)
        assert q.recv() == 1
        d.send(2)
        d.send(3)
        assert q.recv() == 2
        assert q.recv() == 3

    def test_send_timeout(self):
        h = vanilla.Hub()
        d = h.dealer()
        pytest.raises(vanilla.Timeout, d.send, 1, timeout=10)

    def test_recv_timeout(self):
        h = vanilla.Hub()
        d = h.dealer()
        pytest.raises(vanilla.Timeout, d.recv, timeout=10)
        # assert that waiters is cleaned up after timeout
        assert not d.recver.current

    def test_send_select(self):
        h = vanilla.Hub()
        d = h.dealer()

        @h.spawn
        def _():
            ch, _ = h.select([d.sender])
            assert ch == d.sender
            d.send(1)

        h.sleep(1)
        assert d.recv() == 1

    def test_recv_select(self):
        h = vanilla.Hub()

        d = h.dealer()
        q = h.queue(10)

        def selector():
            ch, item = h.select([d.recver])
            assert ch == d.recver
            q.send(item)

        h.spawn(selector)
        h.spawn(selector)
        h.spawn(selector)
        h.sleep(1)

        d.send(1)
        assert q.recv() == 1
        d.send(2)
        d.send(3)
        assert q.recv() == 2
        assert q.recv() == 3


class TestRouter(object):
    def test_send_then_recv(self):
        h = vanilla.Hub()
        r = h.router()

        h.spawn(r.send, 3)
        h.spawn(r.send, 2)
        h.spawn(r.send, 1)
        h.sleep(1)

        assert r.recv() == 3
        assert r.recv() == 2
        assert r.recv() == 1

    def test_recv_then_send(self):
        h = vanilla.Hub()

        r = h.router()
        q = h.queue(10)

        @h.spawn
        def _():
            q.send(r.recv())

        h.sleep(1)
        r.send(1)
        assert q.recv() == 1

    def test_pipe(self):
        h = vanilla.Hub()

        r = h.router()

        p1 = h.pipe()
        p2 = h.pipe()

        p1.pipe(r)
        p2.pipe(r)

        h.spawn(p1.send, 1)
        h.spawn(p2.send, 2)
        h.spawn(p1.send, 1)
        h.spawn(p2.send, 2)

        assert r.recv() == 1
        assert r.recv() == 2
        assert r.recv() == 1
        assert r.recv() == 2


class TestChannel(object):
    def test_send_then_recv(self):
        h = vanilla.Hub()
        ch = h.channel()

        h.spawn(ch.send, 3)
        h.spawn(ch.send, 2)
        h.spawn(ch.send, 1)
        h.sleep(1)

        assert ch.recv() == 3
        assert ch.recv() == 2
        assert ch.recv() == 1

    def test_recv_then_send(self):
        h = vanilla.Hub()

        d = h.dealer()
        q = h.queue(10)

        h.spawn(lambda: q.send(d.recv()))
        h.spawn(lambda: q.send(d.recv()))
        h.spawn(lambda: q.send(d.recv()))
        h.sleep(1)

        d.send(1)
        assert q.recv() == 1
        d.send(2)
        d.send(3)
        assert q.recv() == 2
        assert q.recv() == 3

    def test_no_queue(self):
        h = vanilla.Hub()
        ch = h.channel()
        pytest.raises(vanilla.Timeout, ch.send, 1, timeout=0)

    def test_queue(self):
        h = vanilla.Hub()
        ch = h.channel(2)
        ch.send(1, timeout=0)
        ch.send(2, timeout=0)
        pytest.raises(vanilla.Timeout, ch.send, 3, timeout=0)
        assert ch.recv() == 1
        ch.send(3, timeout=0)
        assert ch.recv() == 2
        assert ch.recv() == 3


class TestBroadcast(object):
    def test_broadcast(self):
        h = vanilla.Hub()

        b = h.broadcast()
        check = h.queue(10)

        b.onempty(check.send, 'empty')

        def subscriber(s, name):
            for item in s:
                check.send((name, item))

        s1 = b.subscribe()
        s2 = b.subscribe()
        h.spawn(subscriber, s1, 's1')
        h.spawn(subscriber, s2, 's2')
        h.sleep(1)

        b.send(1)
        assert check.recv() == ('s1', 1)
        assert check.recv() == ('s2', 1)

        b.send(2)
        assert check.recv() == ('s1', 2)
        assert check.recv() == ('s2', 2)

        s1.close()
        b.send(3)
        assert check.recv() == ('s2', 3)
        pytest.raises(vanilla.Timeout, check.recv, timeout=0)

        s2.close()
        assert check.recv() == 'empty'

    def test_pipe(self):
        h = vanilla.Hub()

        b = h.broadcast()
        source = h.pulse(20)
        source.pipe(b)
        check = h.queue(10)

        def subscriber(s, name):
            for item in s:
                check.send((name, item))

        s1 = b.subscribe()
        s2 = b.subscribe()

        h.spawn(subscriber, s1, 's1')
        h.spawn(subscriber, s2, 's2')
        h.sleep(1)

        assert check.recv() == ('s1', True)
        assert check.recv() == ('s2', True)


class TestState(object):
    def test_state(self):
        h = vanilla.Hub()

        s = h.state()
        pytest.raises(vanilla.Timeout, s.recv, 10)

        h.spawn_later(10, s.send, 'Toby')
        assert s.recv() == 'Toby'
        assert s.recv() == 'Toby'

        s.clear()
        pytest.raises(vanilla.Timeout, s.recv, 10)
        s.send('Toby')
        assert s.recv() == 'Toby'

    def test_pipe(self):
        h = vanilla.Hub()
        p = h.pipe() \
            .map(lambda x: x*2) \
            .pipe(h.state('Toby')) \
            .map(lambda x: x+'.')

        assert p.recv() == 'Toby.'

        p.send('foo')
        assert p.recv() == 'foofoo.'
        assert p.recv() == 'foofoo.'
        # TODO: should clear be able to be passed through map?


class TestSerialize(object):
    def test_serialize(self):
        h = vanilla.Hub()

        out = h.pipe()

        @h.serialize
        def go(i):
            h.sleep(40-(10*i))
            out.send(i)

        for i in xrange(3):
            h.spawn(go, i)

        assert list(out.recver) == [0, 1, 2]

    def test_exception(self):
        h = vanilla.Hub()

        @h.serialize
        def go():
            raise AssertionError('foo')

        pytest.raises(AssertionError, go)


class TestStream(object):
    def test_stream(self):
        h = vanilla.Hub()

        sender, recver = h.pipe()
        recver = vanilla.message.Stream(recver)

        @h.spawn
        def _():
            sender.send('foo')
            sender.send('123')
            sender.send('456')
            sender.send('TobyTobyToby')
            sender.send('foo\n')
            sender.send('bar\nend.')
            sender.close()

        assert recver.recv() == 'foo'
        assert recver.recv_n(2) == '12'
        assert recver.recv_n(2) == '34'
        assert recver.recv_partition('y') == '56Tob'
        assert recver.recv_partition('y') == 'Tob'
        assert recver.recv_line() == 'Tobyfoo'
        assert recver.recv_line() == 'bar'
        assert recver.recv() == 'end.'
        pytest.raises(vanilla.Closed, recver.recv_n, 2)
