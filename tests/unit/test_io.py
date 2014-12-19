import os

import pytest

import vanilla


# TODO: remove
import logging
logging.basicConfig()


class TestPoll(object):
    def test_poll(self):
        poll = vanilla.Poll()

        r, w = os.pipe()

        poll.register(r, vanilla.POLLIN)
        assert poll.poll(timeout=0) == []

        os.write(w, '1')
        assert poll.poll() == [(r, vanilla.POLLIN)]
        # test event is cleared
        assert poll.poll(timeout=0) == []

        # test event is reset on new write after read
        assert os.read(r, 4096) == '1'
        assert poll.poll(timeout=0) == []
        os.write(w, '2')
        assert poll.poll() == [(r, vanilla.POLLIN)]
        assert poll.poll(timeout=0) == []

        # test event is reset on new write without read
        os.write(w, '3')
        assert poll.poll() == [(r, vanilla.POLLIN)]
        assert poll.poll(timeout=0) == []

        assert os.read(r, 4096) == '23'


class TestIO(object):
    def test_pipe(self):
        print
        print
        h = vanilla.Hub()
        sender, recver = h.io.pipe()
        sender.send('123')
        h.sleep(10000)
        assert recver.recv() == '123'

    def test_eagain(self):
        return
        h = vanilla.Hub()
        sender, recver = h.io.pipe()
        assert recver.recv() == '123'

    """
    def test_read_partition(self):
        h = vanilla.Hub()
        r, w = os.pipe()

        r = h.poll.fileno(r)
        w = h.poll.fileno(w)

        w.write('12\r\n3')
        assert r.read_partition('\r\n') == '12'

        h.spawn_later(10, w.write, '2\r\n')
        assert r.read_partition('\r\n') == '32'

    def test_write_eagain(self):
        h = vanilla.Hub()
        r, w = os.pipe()

        r = h.poll.fileno(r)
        w = h.poll.fileno(w)

        want = 'x' * 1024 * 1024
        w.write(want)
        got = r.read_bytes(len(want))
        assert want == got

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

    def test_close_write(self):
        h = vanilla.Hub()
        r, w = os.pipe()

        r = h.poll.fileno(r)
        w = h.poll.fileno(w)

        w.write('123')
        assert r.read_bytes(2) == '12'

        os.close(w.d.fileno())
        w.write('2')
        pytest.raises(vanilla.Closed, w.write, '3')

        assert r.read_bytes(1) == '3'
        pytest.raises(vanilla.Closed, r.read)

    def test_stop(self):
        h = vanilla.Hub()
        r, w = os.pipe()

        r = h.poll.fileno(r)
        w = h.poll.fileno(w)

        h.stop()
    """
