import vanilla


def test_call():
    def add(a, b):
        return a + b

    h = vanilla.Hub()
    assert h.thread.call(add, 2, 3).recv() == 5
