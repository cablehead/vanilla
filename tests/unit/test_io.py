import pytest

import vanilla


# TODO: remove
import logging
logging.basicConfig()


class TestIO(object):
    def test_pipe(self):
        h = vanilla.Hub()
        sender, recver = h.io.pipe()
        pytest.raises(vanilla.Timeout, recver.recv, timeout=0)
        sender.send('123')
        assert recver.recv() == '123'
        h.stop()

    def test_write_eagain(self):
        h = vanilla.Hub()
        sender, recver = h.io.pipe()

        want = 'x' * 1024 * 1024

        @h.spawn
        def _():
            sender.send(want)

        got = ''
        while len(got) < len(want):
            got += recver.recv()
        assert want == got

    def test_write_serialize(self):
        h = vanilla.Hub()
        sender, recver = h.io.pipe()

        want1 = 'a' * 1024 * 1024
        want2 = 'b' * 1024 * 1024

        @h.spawn
        def _():
            sender.send(want1)

        @h.spawn
        def _():
            sender.send(want2)

        got = ''
        while len(got) < (len(want1) + len(want2)):
            got += recver.recv()
        assert got == want1+want2

    def test_write_close(self):
        h = vanilla.Hub()
        sender, recver = h.io.pipe()

        sender.send('123')
        h.sleep(1)
        sender.send('456')

        sender.close()
        pytest.raises(vanilla.Closed, sender.send, '789')

        assert recver.recv() == '123'
        assert recver.recv() == '456'
        pytest.raises(vanilla.Halt, recver.recv)
        h.sleep(1)
        assert not h.registered

    def test_read_close(self):
        h = vanilla.Hub()
        sender, recver = h.io.pipe()
        recver.close()
        pytest.raises(vanilla.Closed, sender.send, '123')
        pytest.raises(vanilla.Closed, recver.recv)
        assert not h.registered

    def test_api(self):
        h = vanilla.Hub()
        p1 = h.io.pipe()
        p2 = h.io.pipe()

        p1.pipe(p2)
        p3 = p2.map(lambda x: int(x)*2)

        p1.send('3')
        assert p3.recv() == 6

    def test_stream(self):
        h = vanilla.Hub()
        p = h.io.pipe()
        h.spawn(p.send, '12foo\n')
        assert p.recv_n(2) == '12'
        assert p.recv_line(2) == 'foo'
