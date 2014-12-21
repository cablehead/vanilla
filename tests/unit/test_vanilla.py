import signal
import time
import os
import gc

import pytest

import vanilla

from vanilla import protocols


# TODO: remove
import logging
logging.basicConfig()


def test_lazy():
    class C(object):
        @vanilla.lazy
        def now(self):
            return time.time()

    c = C()
    want = c.now
    time.sleep(0.01)
    assert c.now == want


def test_Scheduler():
    s = vanilla.Scheduler()
    s.add(4, 'f2')
    s.add(9, 'f4')
    s.add(3, 'f1')
    item3 = s.add(7, 'f3')

    assert 0.003 - s.timeout() < 0.001
    assert len(s) == 4

    s.remove(item3)
    assert 0.003 - s.timeout() < 0.001
    assert len(s) == 3

    assert s.pop() == ('f1', ())
    assert 0.004 - s.timeout() < 0.001
    assert len(s) == 2

    assert s.pop() == ('f2', ())
    assert 0.009 - s.timeout() < 0.001
    assert len(s) == 1

    assert s.pop() == ('f4', ())
    assert not s


class TestHub(object):
    def test_spawn(self):
        h = vanilla.Hub()
        a = []

        h.spawn_later(10, lambda: a.append(1))
        h.spawn(lambda: a.append(2))

        h.sleep(1)
        assert a == [2]

        h.sleep(10)
        assert a == [2, 1]

    def test_exception(self):
        h = vanilla.Hub()

        def raiser():
            raise Exception()
        h.spawn(raiser)
        h.sleep(1)

        a = []
        h.spawn(lambda: a.append(2))
        h.sleep(1)
        assert a == [2]

    def test_stop(self):
        h = vanilla.Hub()

        @h.spawn
        def _():
            h.sleep(20)

        h.stop()

    def test_stop_on_term(self):
        h = vanilla.Hub()
        h.spawn_later(10, os.kill, os.getpid(), signal.SIGINT)
        h.stop_on_term()


class TestProtocol(object):
    def test_protocol(self):
        h = vanilla.Hub()
        r, w = os.pipe()

        r = h.poll.fileno(r)
        w = h.poll.fileno(w)

        sender = h.pipe().map(lambda x: x + '\n').pipe(w)

        @r.pipe
        def recver(upstream, downstream):
            received = ''
            while True:
                keep, matched, extra = received.partition('\n')
                if matched:
                    received = extra
                    downstream.send(keep)
                    continue
                received += upstream.recv()

        sender.send('1\n2')
        assert recver.recv() == '1'
        assert recver.recv() == '2'

    def test_length_prefixed(self):
        h = vanilla.Hub()

        @h.tcp.listen()
        def server(conn):
            conn = protocols.length_prefix(conn)
            for message in conn.reader.recver:
                conn.writer.send(message*2)

        conn = h.tcp.connect(server.port)
        conn = protocols.length_prefix(conn)

        conn.writer.send('foo')
        conn.writer.send('bar')

        assert conn.reader.recv() == 'foofoo'
        assert conn.reader.recv() == 'barbar'

    def test_json(self):
        h = vanilla.Hub()

        import json

        def jsonencode(conn):
            conn = protocols.length_prefix(conn)
            conn = protocols.map(conn, json.dumps, json.loads)
            return conn

        @h.tcp.listen()
        def server(conn):
            conn = jsonencode(conn)
            for message in conn.reader.recver:
                conn.writer.send(message)

        conn = h.tcp.connect(server.port)
        conn = jsonencode(conn)

        conn.writer.send({'x': 1})
        conn.writer.send({'x': 2})

        assert conn.reader.recv() == {'x': 1}
        assert conn.reader.recv() == {'x': 2}


class TestRequestResponse(object):
    def test_request_response(self):

        class Request(object):
            def __init__(self, hub):
                self.hub = hub
                self.server = self.hub.pipe()

            def call(self, message):
                response = self.hub.pipe()
                self.server.send((message, response.sender))
                return response.recver

        h = vanilla.Hub()

        r = Request(h)

        @h.spawn
        def _():
            request, response = r.server.recv()
            response.send(request*2)

        response = r.call('Toby')
        assert response.recv() == 'TobyToby'

    def test_request_response_over_tcp(self):
        import struct

        REQUEST = 1
        RESPONSE = 2

        class RequestResponse(object):
            def __init__(self, hub, conn):
                self.hub = hub
                self.conn = protocols.length_prefix(conn)
                self.route = 0
                self.outstanding = {}
                self.server = h.pipe()

                @self.hub.spawn
                def _():
                    for message in conn.reader.recver:
                        prefix, message = message[:8], message[8:]
                        typ, route = struct.unpack('<II', prefix)

                        if typ == REQUEST:
                            response = self.hub.pipe()

                            @response.consume
                            def _(message):
                                self.conn.writer.send(
                                    struct.pack('<II', RESPONSE, route) +
                                    message)
                            self.server.send((message, response))

                        elif typ == RESPONSE:
                            response = self.outstanding.pop(route)
                            response.send(message)

            def call(self, message):
                response = self.hub.pipe()
                self.route += 1
                self.outstanding[self.route] = response.sender
                self.conn.writer.send(
                    struct.pack('<II', REQUEST, self.route) + message)
                return response.recver

        h = vanilla.Hub()

        @h.tcp.listen()
        def server(conn):
            conn = RequestResponse(h, conn)
            while True:
                request, response = conn.server.recv()
                response.send(request)

        conn = h.tcp.connect(server.port)
        conn = RequestResponse(h, conn)

        r1 = conn.call('Toby1')
        r2 = conn.call('Toby2')

        assert r1.recv() == 'Toby1'
        assert r2.recv() == 'Toby2'


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

        # TODO:
        return
        # assert that removing the last listener for a signal cleans up the
        # registered file descriptor
        s2.close()
        assert not h.registered


class TestTCP(object):
    def test_tcp(self):
        h = vanilla.Hub()

        @h.tcp.listen()
        def server(conn):
            conn.write(' '.join([conn.read()]*2))

        client = h.tcp.connect(server.port)
        client.write('Toby')
        assert client.read() == 'Toby Toby'

        h.stop()


class TestHTTP(object):
    def test_get_body(self):
        h = vanilla.Hub()

        @h.http.listen()
        def serve(request, response):
            return request.path

        uri = 'http://localhost:%s' % serve.port
        conn = h.http.connect(uri)

        response = conn.get('/')
        response = response.recv()
        assert response.status.code == 200
        assert response.consume() == '/'

        response = conn.get('/toby').recv()
        assert response.status.code == 200
        assert response.consume() == '/toby'

        # TODO: stop!!, everything needs stop testing
        # h.stop()

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
        conn = h.http.connect(uri)

        response = conn.get('/').recv()
        assert response.status.code == 200
        assert list(response.body) == ['0', '1', '2']

        response = conn.get('/peace').recv()
        assert response.status.code == 200
        assert list(response.body) == ['0', '1', '2', 'peace']

        # TODO: stop!!, everything needs stop testing
        # h.stop()

    def test_post(self):
        h = vanilla.Hub()

        @h.http.listen()
        def serve(request, response):
            return request.consume()

        uri = 'http://localhost:%s' % serve.port
        conn = h.http.connect(uri)

        response = conn.post('/').recv()
        assert response.status.code == 200
        assert response.consume() == ''

        response = conn.post('/', data='toby').recv()
        assert response.status.code == 200
        assert response.consume() == 'toby'

    def test_put(self):
        h = vanilla.Hub()

        @h.http.listen()
        def serve(request, response):
            return request.method + request.consume()

        uri = 'http://localhost:%s' % serve.port
        conn = h.http.connect(uri)

        response = conn.put('/').recv()
        assert response.status.code == 200
        assert response.consume() == 'PUT'

        response = conn.put('/', data='toby').recv()
        assert response.status.code == 200
        assert response.consume() == 'PUTtoby'

    def test_delete(self):
        h = vanilla.Hub()

        @h.http.listen()
        def serve(request, response):
            return request.method

        uri = 'http://localhost:%s' % serve.port
        conn = h.http.connect(uri)

        response = conn.delete('/').recv()
        assert response.status.code == 200
        assert response.consume() == 'DELETE'

    def test_404(self):
        h = vanilla.Hub()

        @h.http.listen()
        def serve(request, response):
            raise response.HTTP404

        uri = 'http://localhost:%s' % serve.port
        response = h.http.connect(uri).get('/').recv()
        assert response.status.code == 404

    def test_overlap(self):
        h = vanilla.Hub()

        @h.http.listen()
        def serve(request, response):
            t = request.path[1:]
            h.sleep(int(t))
            return t

        q = h.queue(10)

        uri = 'http://localhost:%s' % serve.port
        conn = h.http.connect(uri)

        def go(t):
            t = str(t)
            r = conn.get('/'+t).recv()
            q.send(int(r.consume()))

        h.spawn(go, 50)
        h.spawn(go, 20)

        assert q.recv() == 50
        assert q.recv() == 20

    def test_basic_auth(self):
        h = vanilla.Hub()

        @h.http.listen()
        def serve(request, response):
            return request.headers['Authorization']

        uri = 'http://localhost:%s' % serve.port
        conn = h.http.connect(uri)

        response = conn.get('/', auth=('foo', 'bar'))
        response = response.recv()
        assert response.consume() == 'Basic Zm9vOmJhcg=='

    def test_connection_lost(self):
        h = vanilla.Hub()

        @h.http.listen()
        def serve(request, response):
            conn.socket.close()
            return '.'

        uri = 'http://localhost:%s' % serve.port
        conn = h.http.connect(uri)

        response = conn.get('/')
        pytest.raises(vanilla.ConnectionLost, response.recv)


class TestWebsocket(object):
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

        gc.collect()

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

        # test we can call select on the websocket
        message = 'x' * 125
        ws.send(message)
        assert h.select([ws.recver]) == (ws.recver, message)

    def test_websocket_end(self):
        h = vanilla.Hub()

        @h.http.listen()
        def serve(request, response):
            ws = response.upgrade()
            ws.recv()
            return

        uri = 'ws://localhost:%s' % serve.port
        ws = h.http.connect(uri).websocket('/')
        ws.send('1')
        pytest.raises(vanilla.Closed, ws.recv)
