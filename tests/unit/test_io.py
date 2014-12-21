import os

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
        pytest.raises(vanilla.Closed, recver.recv)

    def test_read_close(self):
        h = vanilla.Hub()
        sender, recver = h.io.pipe()
        recver.close()
        pytest.raises(vanilla.Closed, sender.send, '123')
        pytest.raises(vanilla.Closed, recver.recv)


    """
    def test_close_read(self):
        h = vanilla.Hub()
        r, w = os.pipe()

        r = h.poll.fileno(r)
        w = h.poll.fileno(w)

        w.write('123')
        assert r.read_bytes(2) == '12'

        os.close(r.d.fileno())
        w.write('2')
        pytest.raises(vanilla.Closed, w.write, '3')

        assert r.read_bytes(1) == '3'
        pytest.raises(vanilla.Closed, r.read)
    """
