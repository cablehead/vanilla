import vanilla
import signal
import os

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

    def test_unexecutable(self):
        h = vanilla.Hub()
        child = h.process.execv(['/usr/bin/env', 'grep123'])
        child.done.recv()
        assert child.exitcode == 127

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
        child.done.recv()
        assert not child.check_liveness()

    def test_env(self):
        h = vanilla.Hub()

        VAR1 = 'VANILLA_%s_VAR1' % os.getpid()
        VAR2 = 'VANILLA_%s_VAR2' % os.getpid()

        os.putenv(VAR1, 'VAR1')

        child = h.process.execv(
            ['/usr/bin/env', 'sh', '-c', 'echo $%s $%s' % (VAR1, VAR2)])
        assert child.stdout.recv() == 'VAR1\n'

        child = h.process.execv(
            ['/usr/bin/env', 'sh', '-c', 'echo $%s $%s' % (VAR1, VAR2)],
            env={VAR2: 'VAR2'})
        assert child.stdout.recv() == 'VAR2\n'

    def test_spawn(self):
        h = vanilla.Hub()

        def worker():
            import sys
            while True:
                line = sys.stdin.readline()
                sys.stdout.write('worker: %s' % line)

        child = h.process.spawn(worker)
        child.stdin.send('line1\n')
        assert child.stdout.recv_partition('\n') == 'worker: line1'
        child.stdin.send('line2\n')
        assert child.stdout.recv_partition('\n') == 'worker: line2'
