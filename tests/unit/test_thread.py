import time

import vanilla


# TODO: test shutdown

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
