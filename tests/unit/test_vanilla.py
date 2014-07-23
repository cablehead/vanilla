import time
import os
import gc

import pytest

import vanilla


class TestHub(object):
    def test_spawn(self):
        h = vanilla.Hub()
        a = []

        h.spawn_later(10, lambda: a.append(1))
        h.spawn(lambda: a.append(2))

        h.sleep(1)
        assert a == [2]

        h.sleep(10)
        assert a == [2, 1]

    def test_exception(self):
        h = vanilla.Hub()

        def raiser():
            raise Exception()
        h.spawn(raiser)
        h.sleep(1)

        a = []
        h.spawn(lambda: a.append(2))
        h.sleep(1)
        assert a == [2]


class TestPiping(object):
    def test_timeout(self):
        h = vanilla.Hub()

        sender, recver = h.pipe()
        check_sender, check_recver = h.pipe()

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

    def test_select(self):
        h = vanilla.Hub()

        s1, r1 = h.pipe()
        s2, r2 = h.pipe()
        check_s, check_r = h.pipe()

        @h.spawn
        def _():
            check_s.send(r1.recv())

        @h.spawn
        def _():
            s2.send(10)
            check_s.send('done')

        ch, item = h.select([s1, r2])
        assert ch == s1
        s1.send(20)

        ch, item = h.select([s1, r2])
        assert ch == r2
        assert item == 10

        assert check_r.recv() == 20
        assert check_r.recv() == 'done'

    def test_select_timeout(self):
        h = vanilla.Hub()

        s1, r1 = h.pipe()
        s2, r2 = h.pipe()
        check_s, check_r = h.pipe()

        pytest.raises(vanilla.Timeout, h.select, [s1, r2], timeout=0)

        @h.spawn
        def _():
            h.sleep(20)
            check_s.send(r1.recv())

        pytest.raises(vanilla.Timeout, h.select, [s1, r2], timeout=10)

        ch, item = h.select([s1, r2], timeout=20)
        assert ch == s1
        s1.send(20)
        assert check_r.recv() == 20

        @h.spawn
        def _():
            h.sleep(20)
            s2.send(10)
            check_s.send('done')

        pytest.raises(vanilla.Timeout, h.select, [s1, r2], timeout=10)

        ch, item = h.select([s1, r2], timeout=20)
        assert ch == r2
        assert item == 10
        assert check_r.recv() == 'done'

    def test_abandoned_sender(self):
        h = vanilla.Hub()

        check_sender, check_recver = h.pipe()

        # test abondoned after pause
        sender, recver = h.pipe()

        @h.spawn
        def _():
            pytest.raises(vanilla.Abandoned, sender.send, 10)
            check_sender.send('done')

        # sleep so the spawn runs and the send pauses
        h.sleep(1)
        del recver
        gc.collect()
        assert check_recver.recv() == 'done'

        # test abondoned before pause
        sender, recver = h.pipe()

        @h.spawn
        def _():
            pytest.raises(vanilla.Abandoned, sender.send, 10)
            check_sender.send('done')

        del recver
        gc.collect()
        assert check_recver.recv() == 'done'

    def test_abandoned_recver(self):
        h = vanilla.Hub()

        check_sender, check_recver = h.pipe()

        # test abondoned after pause
        sender, recver = h.pipe()

        @h.spawn
        def _():
            pytest.raises(vanilla.Abandoned, recver.recv)
            check_sender.send('done')

        # sleep so the spawn runs and the recv pauses
        h.sleep(1)
        del sender
        gc.collect()
        assert check_recver.recv() == 'done'

        # test abondoned before pause
        sender, recver = h.pipe()

        @h.spawn
        def _():
            pytest.raises(vanilla.Abandoned, recver.recv)
            check_sender.send('done')

        del sender
        gc.collect()
        assert check_recver.recv() == 'done'

    def test_stream(self):
        h = vanilla.Hub()

        @h.stream
        def counter(sender):
            for i in xrange(10):
                sender.send(i)

        assert counter.recv() == 0
        h.sleep(10)
        assert counter.recv() == 1

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

        # TODO: test abandoned

    """
    def test_buffer(self):
        h = vanilla.Hub()
        sender, recver = buffer(h, 2)
        sender.send(1)
        sender.send(2)
        assert recver.recv() == 1
        assert recver.recv() == 2
    """


class TestDescriptor(object):
    def test_core(self):
        h = vanilla.Hub()
        r, w = os.pipe()

        r = h.poll.fileno(r)

        os.write(w, '1')
        h.sleep(10)
        assert r.recv() == '1'

        os.write(w, '2')
        h.sleep(10)
        assert r.recv() == '2'


def test_lazy():
    class C(object):
        @vanilla.lazy
        def now(self):
            return time.time()

    c = C()
    want = c.now
    time.sleep(0.01)
    assert c.now == want


def test_Scheduler():
    s = vanilla.Scheduler()
    s.add(4, 'f2')
    s.add(9, 'f4')
    s.add(3, 'f1')
    item3 = s.add(7, 'f3')

    assert 0.003 - s.timeout() < 0.0005
    assert len(s) == 4

    s.remove(item3)
    assert 0.003 - s.timeout() < 0.0005
    assert len(s) == 3

    assert s.pop() == ('f1', ())
    assert 0.004 - s.timeout() < 0.0005
    assert len(s) == 2

    assert s.pop() == ('f2', ())
    assert 0.009 - s.timeout() < 0.0005
    assert len(s) == 1

    assert s.pop() == ('f4', ())
    assert not s
