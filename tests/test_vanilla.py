import socket
import signal
import json
import time


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


def test_HTTPClient():
    # TODO: Just using httpbin until the HTTP Server side of Vanilla is cleaned
    # up. There should be an integration suite that could still use httpbin.
    h = vanilla.Hub()

    conn = h.http.connect('http://httpbin.org')

    get1 = conn.get('/get', params={'foo': 'bar'})
    drip = conn.get('/drip', params={'numbytes': 3, 'duration': 3, 'delay': 1})
    get2 = conn.get('/get', params={'foo': 'bar2'})

    status, headers, body = list(get1)
    assert status.code == 200
    assert json.loads(body)['args'] == {'foo': 'bar'}

    # assert the first payload from drip takes roughly a second
    start = time.time()
    assert drip.recv().code == 200
    took, start = time.time() - start, time.time()
    assert 1.5 > took > 1

    # assert we're getting a chunked response, and the headers came immediately
    assert drip.recv()['transfer-encoding'] == 'chunked'
    took, start = time.time() - start, time.time()
    assert took < 0.0002

    # the first chunk also comes immediately
    assert drip.recv() == '*'
    took, start = time.time() - start, time.time()
    assert took < 0.002

    # check remaining chunks come every second
    for item in drip:
        took, start = time.time() - start, time.time()
        assert item == '*'
        assert 1.1 > took > .9

    # and finally another second for the server to end the response
    took, start = time.time() - start, time.time()
    assert 1.1 > took > .9

    status, headers, body = list(get2)
    assert status.code == 200
    assert json.loads(body)['args'] == {'foo': 'bar2'}


def test_Stream():
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
    stream = vanilla.Stream(h, conn)

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

    assert stream.recv_bytes(5) == '12121'
    assert stream.recv_bytes(5) == '21212'
    assert stream.recv_bytes(5) == '12121'
    assert stream.recv_partition('\r\n') == '2foo'
    assert stream.recv_partition('\r\n') == 'bar'
    assert stream.recv_partition('\r\n') == ''

    # h.stop_on_term()


class TestHTTP(object):
    def test_get_basic(self):
        h = vanilla.Hub()

        @h.http.listen(8000)
        def serve(request, response):
            if len(request.path) > 1:
                return request.path[1:]

        response = h.http.connect('http://localhost:8000').get('/')
        assert response.recv().code == 200
        response.recv()
        assert response.recv() == ''

        response = h.http.connect('http://localhost:8000').get('/toby')
        assert response.recv().code == 200
        response.recv()
        assert response.recv() == 'toby'

        h.stop()

    def test_get_chunked(self):
        h = vanilla.Hub()

        @h.http.listen(8000)
        def serve(request, response):
            for i in xrange(3):
                h.sleep(10)
                response.send(str(i))
            if len(request.path) > 1:
                return request.path[1:]

        response = h.http.connect('http://localhost:8000').get('/')
        got = list(response)
        assert got[0].code == 200
        assert got[2:] == ['0', '1', '2']

        response = h.http.connect('http://localhost:8000').get('/peace')
        got = list(response)
        assert got[0].code == 200
        assert got[2:] == ['0', '1', '2', 'peace']

        h.stop()
