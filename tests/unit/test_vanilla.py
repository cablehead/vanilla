import socket
import signal


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

    # test pipeline
    @c
    def _(x):
        if x % 2:
            raise vanilla.Filter
        return x * 2

    # assert exceptions are propogated
    c.send('123')
    pytest.raises(TypeError, c.recv)

    # odd numbers are filtered
    c.send(5)
    pytest.raises(vanilla.Timeout, c.recv, timeout=0)

    # success
    c.send(2)
    assert 4 == c.recv(timeout=0)

    # test closing the channel and channel iteration
    for i in xrange(10):
        c.send(i)
    c.close()
    assert list(c) == [0, 4, 8, 12, 16]


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

    fh = tmpdir.join('f1').open('w')
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

    tmpdir.join('d', 'f2').open('w').write('data')

    ch, (mask, name) = h.select(ch1, ch2)
    assert ch == ch2
    assert name == 'f2'
    assert inot.humanize_mask(mask) == ['create']

    ch, (mask, name) = h.select(ch1, ch2)
    assert ch == ch2
    assert name == 'f2'
    assert inot.humanize_mask(mask) == ['open']

    fh.write('data')
    fh.close()

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


class TestProcess(object):
    def test_spawn(self):
        h = vanilla.Hub()

        def child(code):
            import sys
            sys.exit(code)

        p = h.process.spawn(child, 202)
        p.done.recv()
        assert p.exitcode == 202


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


def test_FD():
    h = vanilla.Hub()

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(('127.0.0.1', 0))
    s.listen(socket.SOMAXCONN)

    port = s.getsockname()[1]

    client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    client.connect(('127.0.0.1', port))

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
            client.sendall(chunk)

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
