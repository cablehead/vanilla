import vanilla


def test_process():
    h = vanilla.Hub()
    child = h.process.execv(['/usr/bin/env', 'grep', '--line-buffered', 'foo'])
    child.stdin.send('foo1\n')
    assert child.stdout.recv() == 'foo1\n'
    child.stdin.send('bar1\n')
    child.stdin.send('foo2\n')
    assert child.stdout.recv() == 'foo2\n'
