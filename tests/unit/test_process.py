import vanilla
import signal


class TestProcess(object):
    def test_signal(self):
        h = vanilla.Hub()
        child = h.process.execv(
            ['/usr/bin/env', 'grep', '--line-buffered', 'foo'])
        child.signal(signal.SIGTERM)
        assert not child.check_liveness()

    def test_basic(self):
        h = vanilla.Hub()
        child = h.process.execv(
            ['/usr/bin/env', 'grep', '--line-buffered', 'foo'])
        child.stdin.send('foo1\n')
        assert child.stdout.recv() == 'foo1\n'
        child.stdin.send('bar1\n')
        child.stdin.send('foo2\n')
        assert child.stdout.recv() == 'foo2\n'

    def test_stderr(self):
        h = vanilla.Hub()
        child = h.process.execv(['/usr/bin/env', 'grep', '-g'])
        assert child.stderr.recv()

    def test_stderrtoout(self):
        h = vanilla.Hub()
        child = h.process.execv(
            ['/usr/bin/env', 'grep', '-g'], stderrtoout=True)
        assert child.stdout.recv()
