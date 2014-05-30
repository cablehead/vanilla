import signal
import pytest


import vanilla


class CheckException(Exception):
    pass


def test_basics():
    h = vanilla.Hub()
    a = []

    h.spawn_later(10, lambda: a.append(1))
    h.spawn(lambda: a.append(2))

    h.sleep(1)
    assert a == [2]

    h.sleep(10)
    assert a == [2, 1]


def test_Event():
    h = vanilla.Hub()
    e = h.event()
    h.spawn_later(10, e.set)
    e.wait()

    # assert that new waiters after a clear will block until the next set
    e.clear()
    done = h.event()

    @h.spawn
    def _():
        e.wait()
        e.clear().wait()
        done.set()

    h.sleep(1)
    e.set()
    assert not done
    e.set()
    assert done


def test_preserve_exception():
    try:
        raise CheckException('oh hai')
    except CheckException:
        e = vanilla.preserve_exception()

    pytest.raises(CheckException, e.reraise)


def test_Channel():
    h = vanilla.Hub()
    c = h.channel()

    # test send before receive
    c.send('123')
    assert '123' == c.recv()

    # test receive before send
    h.spawn_later(10, c.send, '123')
    assert '123' == c.recv()

    # test timeout
    h.spawn_later(10, c.send, '123')
    pytest.raises(vanilla.Timeout, c.recv, timeout=5)
    assert c.recv(timeout=10) == '123'

    # test preserving exception details
    try:
        raise CheckException('oh hai')
    except:
        c.throw()
    pytest.raises(CheckException, c.recv)

    # test pipeline
    @c
    def _(x):
        if x % 2:
            raise vanilla.Filter
        return x * 2

    # assert exceptions are propogated
    c.send('123')
    pytest.raises(TypeError, c.recv)

    # odd numbers are filtered
    c.send(5)
    pytest.raises(vanilla.Timeout, c.recv, timeout=0)

    # success
    c.send(2)
    assert 4 == c.recv(timeout=0)

    # test closing the channel and channel iteration
    for i in xrange(10):
        c.send(i)
    c.close()
    assert list(c) == [0, 4, 8, 12, 16]


def test_Signal():
    h = vanilla.Hub()

    signal.setitimer(signal.ITIMER_REAL, 10.0/1000)
    ch1 = h.signal.subscribe(signal.SIGALRM)
    ch2 = h.signal.subscribe(signal.SIGALRM)

    assert ch1.recv() == signal.SIGALRM
    assert ch2.recv() == signal.SIGALRM

    signal.setitimer(signal.ITIMER_REAL, 10.0/1000)
    h.signal.unsubscribe(ch1)

    pytest.raises(vanilla.Timeout, ch1.recv, timeout=12)
    assert ch2.recv() == signal.SIGALRM

    # assert that removing the last listener for a signal cleans up the
    # registered file descriptor
    h.signal.unsubscribe(ch2)
    assert not h.registered


def test_stop():
    """
    test that all components cleanly shutdown when the hub is requested to stop
    """
    h = vanilla.Hub()
    h.signal.subscribe(signal.SIGALRM)
    h.stop()
    assert not h.registered


def test_Scheduler():
    s = vanilla.Scheduler()
    s.add(4, 'f2')
    s.add(9, 'f4')
    s.add(3, 'f1')
    item3 = s.add(7, 'f3')

    assert 0.003 - s.timeout() < 0.0002
    assert len(s) == 4

    s.remove(item3)
    assert 0.003 - s.timeout() < 0.0002
    assert len(s) == 3

    assert s.pop() == ('f1', ())
    assert 0.004 - s.timeout() < 0.0002
    assert len(s) == 2

    assert s.pop() == ('f2', ())
    assert 0.009 - s.timeout() < 0.0002
    assert len(s) == 1

    assert s.pop() == ('f4', ())
    assert not s
