import os

import vanilla.poll


class TestPoll(object):
    def test_poll(self):
        poll = vanilla.poll.Poll()

        r, w = os.pipe()

        poll.register(r, vanilla.poll.POLLIN)
        assert poll.poll(timeout=0) == []

        os.write(w, '1')
        assert poll.poll() == [(r, vanilla.poll.POLLIN)]
        # test event is cleared
        assert poll.poll(timeout=0) == []

        # test event is reset on new write after read
        assert os.read(r, 4096) == '1'
        assert poll.poll(timeout=0) == []
        os.write(w, '2')
        assert poll.poll() == [(r, vanilla.poll.POLLIN)]
        assert poll.poll(timeout=0) == []

        # test event is reset on new write without read
        os.write(w, '3')
        assert poll.poll() == [(r, vanilla.poll.POLLIN)]
        assert poll.poll(timeout=0) == []

        assert os.read(r, 4096) == '23'

    def test_write_close(self):
        poll = vanilla.poll.Poll()
        r, w = os.pipe()

        poll.register(r, vanilla.poll.POLLIN)
        poll.register(w, vanilla.poll.POLLOUT)
        assert poll.poll() == [(w, vanilla.poll.POLLOUT)]
        assert poll.poll(timeout=0) == []

        os.close(w)
        assert poll.poll() == [(r, vanilla.poll.POLLERR)]
        assert poll.poll(timeout=0) == []

    def test_read_close(self):
        poll = vanilla.poll.Poll()
        r, w = os.pipe()

        poll.register(r, vanilla.poll.POLLIN)
        poll.register(w, vanilla.poll.POLLOUT)
        assert poll.poll() == [(w, vanilla.poll.POLLOUT)]
        assert poll.poll(timeout=0) == []

        os.close(r)
        got = poll.poll()
        assert got == [(w, vanilla.poll.POLLERR)]
        assert poll.poll(timeout=0) == []
