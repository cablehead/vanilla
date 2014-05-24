import vanilla


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
