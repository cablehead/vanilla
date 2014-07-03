import socket
import signal
import time
import os


import pytest


import vanilla


class CheckException(Exception):
    pass


def test_basics():
    h = vanilla.Hub()
    a = []

    h.spawn_later(10, lambda: a.append(1))
    h.spawn(lambda: a.append(2))

    h.sleep(1)
    assert a == [2]

    h.sleep(10)
    assert a == [2, 1]


def test_Event():
    h = vanilla.Hub()
    e = h.event()
    h.spawn_later(10, e.set)
    e.wait()

    # assert that new waiters after a clear will block until the next set
    e.clear()
    done = h.event()

    @h.spawn
    def _():
        e.wait()
        e.clear().wait()
        done.set()

    h.sleep(1)
    e.set()
    assert not done
    e.set()
    assert done


def test_preserve_exception():
    try:
        raise CheckException('oh hai')
    except CheckException:
        e = vanilla.preserve_exception()

    pytest.raises(CheckException, e.reraise)


def test_Channel():
    h = vanilla.Hub()
    c = h.channel()

    # test send before receive
    c.send('123')
    assert '123' == c.recv()

    # test receive before send
    h.spawn_later(10, c.send, '123')
    assert '123' == c.recv()

    # test timeout
    h.spawn_later(10, c.send, '123')
    pytest.raises(vanilla.Timeout, c.recv, timeout=5)
    assert c.recv(timeout=10) == '123'

    # test preserving exception details
    try:
        raise CheckException('oh hai')
    except:
        c.throw()
    pytest.raises(CheckException, c.recv)

    # test pipe
    @c.pipe
    def out(c, out):
        for x in c:
            if not x % 2:
                out.send(x*2)

    # assert exceptions are propogated
    c.send('123')
    pytest.raises(TypeError, out.recv)

    # odd numbers are filtered
    c.send(5)
    pytest.raises(vanilla.Timeout, out.recv, timeout=0)

    # success
    c.send(2)
    assert 4 == out.recv(timeout=0)

    # test closing the channel and channel iteration
    for i in xrange(10):
        c.send(i)
    c.close()
    assert list(out) == [0, 4, 8, 12, 16]


def test_select():
    h = vanilla.Hub()
    c1 = h.channel()
    c2 = h.channel()
    check = h.channel()

    def background():
        while True:
            try:
                ch, item = h.select(c1, c2)
                if ch == c1:
                    check.send("c1 " + item)
                    continue
                if ch == c2:
                    check.send("c2 " + item)
                    continue
            except Exception, e:
                c1.close()
                c2.close()
                check.send(e)
                break
    h.spawn(background)

    c1.send("1")
    h.sleep()
    c2.send("2")
    c1.send("3")

    assert "c1 1" == check.recv()
    assert "c2 2" == check.recv()
    assert "c1 3" == check.recv()

    # test select cleans up after an exception
    c1.send(Exception('x'))
    pytest.raises(Exception, check.recv)


def test_select_timeout():
    h = vanilla.Hub()
    c = h.channel()

    @h.spawn
    def _():
        while True:
            h.sleep(20)
            c.send('hi')

    fired, item = h.select(c, timeout=30)
    assert fired == c and item == 'hi'

    pytest.raises(vanilla.Timeout, h.select, c, timeout=5)


def test_Signal():
    h = vanilla.Hub()

    signal.setitimer(signal.ITIMER_REAL, 10.0/1000)

    ch1 = h.signal.subscribe(signal.SIGALRM)
    ch2 = h.signal.subscribe(signal.SIGALRM)

    assert ch1.recv() == signal.SIGALRM
    assert ch2.recv() == signal.SIGALRM

    signal.setitimer(signal.ITIMER_REAL, 10.0/1000)
    h.signal.unsubscribe(ch1)

    pytest.raises(vanilla.Timeout, ch1.recv, timeout=12)
    assert ch2.recv() == signal.SIGALRM

    # assert that removing the last listener for a signal cleans up the
    # registered file descriptor
    h.signal.unsubscribe(ch2)
    assert not h.registered


def test_INotify(tmpdir):
    h = vanilla.Hub()
    inot = h.inotify()
    ch1 = inot.watch(tmpdir.strpath)

    fh1 = tmpdir.join('f1').open('w')
    mask, name = ch1.recv()
    assert name == 'f1'
    assert inot.humanize_mask(mask) == ['create']
    mask, name = ch1.recv()
    assert name == 'f1'
    assert inot.humanize_mask(mask) == ['open']

    tmpdir.mkdir('d')
    mask, name = ch1.recv()
    assert name == 'd'
    assert inot.humanize_mask(mask) == ['create', 'is_dir']

    ch2 = inot.watch(tmpdir.join('d').strpath)

    fh2 = tmpdir.join('d', 'f2').open('w')
    fh2.write('data')
    fh2.close()

    ch, (mask, name) = h.select(ch1, ch2)
    assert ch == ch2
    assert name == 'f2'
    assert inot.humanize_mask(mask) == ['create']

    ch, (mask, name) = h.select(ch1, ch2)
    assert ch == ch2
    assert name == 'f2'
    assert inot.humanize_mask(mask) == ['open']

    fh1.write('data')
    fh1.close()

    ch, (mask, name) = h.select(ch1, ch2)
    assert ch == ch2
    assert name == 'f2'
    assert inot.humanize_mask(mask) == ['modify']

    ch, (mask, name) = h.select(ch1, ch2)
    assert ch == ch2
    assert name == 'f2'
    assert inot.humanize_mask(mask) == ['close_write']

    ch, (mask, name) = h.select(ch1, ch2)
    assert ch == ch1
    assert name == 'f1'
    assert inot.humanize_mask(mask) == ['modify']

    h.stop()


def test_lazy():
    class C(object):
        @vanilla.lazy
        def now(self):
            return time.time()

    c = C()
    want = c.now
    time.sleep(0.01)
    assert c.now == want


class TestProcess(object):
    def test_spawn(self):
        h = vanilla.Hub()

        def child(code):
            import sys
            import vanilla
            h = vanilla.Hub()

            while True:
                try:
                    message = h.stdin.recv_line()
                    h.stdout.send(message+'\n')
                except vanilla.Closed:
                    break

            h.stdout.send('peace.\n')
            sys.exit(code)

        p = h.process.spawn(child, 220, stdin_out=True)

        p.stdin.send('Hi Toby\n')
        p.stdin.send('Hi Toby Toby\n')

        assert p.stdout.recv_line() == 'Hi Toby'
        assert p.stdout.recv_line() == 'Hi Toby Toby'

        p.stdin.close()
        assert p.stdout.recv_line() == 'peace.'

        p.done.recv()
        assert p.exitcode == 220
        assert p.exitsignal == 0

    def test_terminate(self):
        h = vanilla.Hub()

        def child():
            import sys
            import vanilla
            h = vanilla.Hub()
            h.stop_on_term()
            sys.exit(11)

        p = h.process.spawn(child)

        assert p.check_liveness()

        # need to give the child enough time to put it's signal trap in place
        h.sleep(300)
        p.terminate()
        p.done.recv()
        assert p.exitcode == 11
        assert p.exitsignal == 0  # the sigterm was caught

        assert not p.check_liveness()

    def test_execv(self):
        h = vanilla.Hub()

        p = h.process.execv(
            ['/bin/grep', '--line-buffered', 'Toby'], stdin_out=True)

        p.stdin.send('Hi toby\n')
        p.stdin.send('Hi Toby\n')
        assert p.stdout.recv_line() == 'Hi Toby'

        p.stdin.close()
        p.done.recv()
        assert p.exitcode == 0
        assert p.exitsignal == 0


def test_stop():
    """
    test that all components cleanly shutdown when the hub is requested to stop
    """
    h = vanilla.Hub()

    @h.spawn
    def _():
        pytest.raises(vanilla.Stop, h.sleep, 10000)

    signal.setitimer(signal.ITIMER_REAL, 10.0/1000)
    h.signal.subscribe(signal.SIGALRM)

    h.stop()
    assert not h.registered
    assert not h.signal.count


def test_Scheduler():
    s = vanilla.Scheduler()
    s.add(4, 'f2')
    s.add(9, 'f4')
    s.add(3, 'f1')
    item3 = s.add(7, 'f3')

    assert 0.003 - s.timeout() < 0.0002
    assert len(s) == 4

    s.remove(item3)
    assert 0.003 - s.timeout() < 0.0002
    assert len(s) == 3

    assert s.pop() == ('f1', ())
    assert 0.004 - s.timeout() < 0.0002
    assert len(s) == 2

    assert s.pop() == ('f2', ())
    assert 0.009 - s.timeout() < 0.0002
    assert len(s) == 1

    assert s.pop() == ('f4', ())
    assert not s


def test_TCP():
    class Echo(object):
        def __init__(self, hub):
            self.h = hub
            self.s = hub.tcp.listen()
            hub.spawn(self.main)
            self.closed = 0

        def main(self):
            while True:
                conn = self.s.accept.recv()
                self.h.spawn(self.worker, conn)

        def worker(self, conn):
            for route, data in conn.serve:
                conn.reply(route, 'Echo: ' + data)
            self.closed += 1

    h = vanilla.Hub()
    echo = Echo(h)
    c = h.tcp.connect(echo.s.port)
    assert 'Echo: foo' == c.call('foo').recv()

    # test ping / pong
    c.ping()
    c.pong.wait()

    # test connection closing
    assert echo.closed == 0
    c.stop()
    h.sleep(1)
    assert echo.closed == 1


class TestFD(object):
    def test_halfplex(self):
        h = vanilla.Hub()

        pipe_r, pipe_w = os.pipe()
        fd_r = vanilla.FD(h, pipe_r)
        fd_w = vanilla.FD(h, pipe_w)

        fd_w.send('Toby')
        assert fd_r.recv_bytes(4) == 'Toby'

    def test_duplex(self):
        h = vanilla.Hub()

        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(('127.0.0.1', 0))
        s.listen(socket.SOMAXCONN)

        port = s.getsockname()[1]

        client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client.connect(('127.0.0.1', port))
        client_fd = vanilla.FD(h, client.fileno())

        conn, host = s.accept()
        conn.setblocking(0)
        fd = vanilla.FD(h, conn.fileno())

        def chunks(l, n):
            """
            Yield successive n-sized chunks from l.
            """
            for i in xrange(0, len(l), n):
                yield l[i:i+n]

        @h.spawn
        def _():
            for chunk in chunks(('12'*8)+'foo\r\nbar\r\n\r\n', 3):
                h.sleep(10)
                client_fd.send(chunk)

        assert fd.recv_bytes(5) == '12121'
        assert fd.recv_bytes(5) == '21212'
        assert fd.recv_bytes(5) == '12121'
        assert fd.recv_partition('\r\n') == '2foo'
        assert fd.recv_partition('\r\n') == 'bar'
        assert fd.recv_partition('\r\n') == ''

        # h.stop_on_term()


class TestHTTP(object):
    def test_get_basic(self):
        h = vanilla.Hub()

        @h.http.listen()
        def serve(request, response):
            if len(request.path) > 1:
                return request.path[1:]

        uri = 'http://localhost:%s' % serve.port

        response = h.http.connect(uri).get('/')
        assert response.recv().code == 200
        response.recv()
        assert response.recv() == ''

        response = h.http.connect(uri).get('/toby')
        assert response.recv().code == 200
        response.recv()
        assert response.recv() == 'toby'

        h.stop()

    def test_get_chunked(self):
        h = vanilla.Hub()

        @h.http.listen()
        def serve(request, response):
            for i in xrange(3):
                h.sleep(10)
                response.send(str(i))
            if len(request.path) > 1:
                return request.path[1:]

        uri = 'http://localhost:%s' % serve.port

        response = h.http.connect(uri).get('/')
        got = list(response)
        assert got[0].code == 200
        assert got[2:] == ['0', '1', '2']

        response = h.http.connect(uri).get('/peace')
        got = list(response)
        assert got[0].code == 200
        assert got[2:] == ['0', '1', '2', 'peace']

        h.stop()

    def test_get_drop(self):
        # TODO
        return
        h = vanilla.Hub()

        @h.http.listen()
        def serve(request, response):
            for i in xrange(3):
                h.sleep(10)
                response.send(str(i))

        uri = 'http://localhost:%s' % serve.port

        client = h.http.connect(uri)
        response = client.get('/')
        assert response.recv().code == 200
        client.conn.close()

        h.sleep(1000)

    def test_websocket(self):
        h = vanilla.Hub()

        @h.http.listen()
        def serve(request, response):
            ws = response.upgrade()
            while True:
                item = ws.recv()
                ws.send(item)

        uri = 'ws://localhost:%s' % serve.port
        ws = h.http.connect(uri).websocket('/')

        message = 'x' * 125
        ws.send(message)
        assert ws.recv() == message

        message = 'x' * 126
        ws.send(message)
        assert ws.recv() == message

        message = 'x' * 65535
        ws.send(message)
        assert ws.recv() == message

        message = 'x' * 65536
        ws.send(message)
        assert ws.recv() == message


class TestReactive(object):
    """
    experiment with providing a reactive like paradigm to help shape Vanilla's
    API: https://gist.github.com/staltz/868e7e9bc2a7b8c1f754
    """
    def test_clicks(self):
        h = vanilla.Hub()

        clicks = h.channel()

        """
        This interface would be possible. But do we want that?!
        out = (
            clicks
                .buffer(clicks.throttle(10))
                .map(len)
                .filter(lambda x: x >= 2))
        """

        @clicks.pipe
        def count(clicks, out):
            for click in clicks:
                count = 1
                while True:
                    try:
                        clicks.recv(timeout=10)
                        count += 1
                    except vanilla.Timeout:
                        out.send(count)
                        break

        for i in [15, 5, 15, 15, 5, 5, 15, 15]:
            clicks.send('click')
            h.sleep(i)

        assert list(count) == [1, 2, 1, 3, 1]
