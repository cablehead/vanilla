import os

import vanilla


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

    def test_write_close(self):
        poll = vanilla.Poll()
        r, w = os.pipe()

        poll.register(r, vanilla.POLLIN)
        poll.register(w, vanilla.POLLOUT)
        assert poll.poll() == [(w, vanilla.POLLOUT)]
        assert poll.poll(timeout=0) == []

        os.close(w)
        assert poll.poll() == [(r, vanilla.POLLERR)]
        assert poll.poll(timeout=0) == []

    def test_read_close(self):
        poll = vanilla.Poll()
        r, w = os.pipe()

        poll.register(r, vanilla.POLLIN)
        poll.register(w, vanilla.POLLOUT)
        assert poll.poll() == [(w, vanilla.POLLOUT)]
        assert poll.poll(timeout=0) == []

        os.close(r)
        got = poll.poll()
        assert got == [(w, vanilla.POLLERR)]
        assert poll.poll(timeout=0) == []
