import time

import vanilla


# TODO: test shutdown


def test_pipe():
    h = vanilla.Hub()
    sender, recver = h.thread.pipe()
    sender.send(1)
    sender.send(2)
    assert recver.recv() == 1
    assert recver.recv() == 2


def test_call():
    def add(a, b):
        return a + b

    h = vanilla.Hub()
    assert h.thread.call(add, 2, 3).recv() == 5


def test_pool():
    h = vanilla.Hub()

    def sleeper(x):
        time.sleep(x)
        return x

    p = h.thread.pool(2)
    check = h.router()

    p.call(sleeper, 0.2).pipe(check)
    p.call(sleeper, 0.1).pipe(check)
    p.call(sleeper, 0.05).pipe(check)

    assert check.recv() == 0.1
    assert check.recv() == 0.05
    assert check.recv() == 0.2


def test_wrap():

    class Target(object):
        def __init__(self):
            class Two(object):
                def two(self):
                    return "two"
            self.child = Two()

        def one(self):
            return "one"

    target = Target()
    assert target.one() == "one"
    assert target.child.two() == "two"

    h = vanilla.Hub()

    p = h.thread.pool(2)
    w = p.wrap(target)

    assert w.one().recv() == 'one'
    assert w.child.two().recv() == 'two'
