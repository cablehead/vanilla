import signal
import os

import pytest

import vanilla


class TestSignal(object):
    # TODO: test abandoned
    def test_signal(self):
        h = vanilla.Hub()

        signal.setitimer(signal.ITIMER_REAL, 50.0/1000)

        s1 = h.signal.subscribe(signal.SIGALRM)
        s2 = h.signal.subscribe(signal.SIGALRM)

        assert s1.recv() == signal.SIGALRM
        assert s2.recv() == signal.SIGALRM

        signal.setitimer(signal.ITIMER_REAL, 10.0/1000)
        s1.close()

        pytest.raises(vanilla.Halt, s1.recv)
        assert s2.recv() == signal.SIGALRM

        # assert that removing the last listener for a signal cleans up the
        # registered file descriptor
        s2.close()
        assert not h.registered

    def test_stop_on_term(self):
        h = vanilla.Hub()
        h.spawn_later(10, os.kill, os.getpid(), signal.SIGINT)
        h.stop_on_term()
