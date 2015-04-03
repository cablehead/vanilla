import vanilla
import signal

import pytest


class TestProcess(object):
    def test_basic(self):
        h = vanilla.Hub()

        child = h.process.execv(
            ['/usr/bin/env', 'grep', '--line-buffered', 'foo'])
        assert child.check_liveness()
        pytest.raises(vanilla.Timeout, child.done.recv, timeout=0)

        child.stdin.send('foo1\n')
        assert child.stdout.recv() == 'foo1\n'
        child.stdin.send('bar1\n')
        child.stdin.send('foo2\n')
        assert child.stdout.recv() == 'foo2\n'

        child.terminate()
        child.done.recv()
        assert not child.check_liveness()

    def test_stderr(self):
        h = vanilla.Hub()
        child = h.process.execv(['/usr/bin/env', 'grep', '-g'])
        assert child.stderr.recv()

    def test_stderrtoout(self):
        h = vanilla.Hub()
        child = h.process.execv(
            ['/usr/bin/env', 'grep', '-g'], stderrtoout=True)
        assert child.stdout.recv()

    def test_signal(self):
        h = vanilla.Hub()
        child = h.process.execv(
            ['/usr/bin/env', 'grep', '--line-buffered', 'foo'])
        child.signal(signal.SIGTERM)
        # give child a chance to die
        h.sleep(10)
        assert not child.check_liveness()
