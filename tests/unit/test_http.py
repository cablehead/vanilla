import gc

import pytest

import vanilla

import vanilla.http


# TODO: remove
import logging
logging.basicConfig()


class TestHTTP(object):
    def test_get_body(self):
        h = vanilla.Hub()

        serve = h.http.listen()

        @h.spawn
        def _():
            conn = serve.recv()
            for request in conn:
                request.reply(vanilla.http.Status(200), {}, request.path)

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

        serve = h.http.listen()

        @h.spawn
        def _():
            conn = serve.recv()

            for request in conn:
                sender, recver = h.pipe()
                request.reply(vanilla.http.Status(200), {}, recver)

                for i in xrange(3):
                    h.sleep(10)
                    sender.send(str(i))

                if len(request.path) > 1:
                    sender.send(request.path[1:])

                sender.close()

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
