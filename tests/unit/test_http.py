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
        h.stop()
        assert not h.registered

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
        h.stop()
        assert not h.registered

    def test_post(self):
        h = vanilla.Hub()

        serve = h.http.listen()

        @h.spawn
        def _():
            conn = serve.recv()
            for request in conn:
                request.reply(vanilla.http.Status(200), {}, request.consume())

        uri = 'http://localhost:%s' % serve.port
        conn = h.http.connect(uri)

        response = conn.post('/').recv()
        assert response.status.code == 200
        assert response.consume() == ''

        response = conn.post('/', data='toby').recv()
        assert response.status.code == 200
        assert response.consume() == 'toby'
        h.stop()

    def test_post_chunked(self):
        print
        print
        h = vanilla.Hub()

        serve = h.http.listen()

        @h.spawn
        def _():
            conn = serve.recv()
            for request in conn:
                sender, recver = h.pipe()
                request.reply(vanilla.http.Status(200), {}, recver)
                for data in request.body:
                    sender.send(data)
                sender.close()

        uri = 'http://localhost:%s' % serve.port
        conn = h.http.connect(uri)

        sender, recver = h.pipe()

        @h.spawn
        def _():
            for i in xrange(3):
                sender.send(str(i))
                h.sleep(10)
            sender.close()

        response = conn.post('/', data=recver).recv()

        for data in response.body:
            print data

        # h.stop()

    def test_put(self):
        h = vanilla.Hub()

        serve = h.http.listen()

        @h.spawn
        def _():
            conn = serve.recv()
            for request in conn:
                request.reply(
                    vanilla.http.Status(200),
                    {},
                    request.method+request.consume())

        uri = 'http://localhost:%s' % serve.port
        conn = h.http.connect(uri)

        response = conn.put('/').recv()
        assert response.status.code == 200
        assert response.consume() == 'PUT'

        response = conn.put('/', data='toby').recv()
        assert response.status.code == 200
        assert response.consume() == 'PUTtoby'
        h.stop()

    def test_delete(self):
        h = vanilla.Hub()

        serve = h.http.listen()

        @h.spawn
        def _():
            conn = serve.recv()
            for request in conn:
                request.reply(vanilla.http.Status(200), {}, request.method)

        uri = 'http://localhost:%s' % serve.port
        conn = h.http.connect(uri)

        response = conn.delete('/').recv()
        assert response.status.code == 200
        assert response.consume() == 'DELETE'
        h.stop()

    def test_404(self):
        h = vanilla.Hub()

        serve = h.http.listen()

        @h.spawn
        def _():
            conn = serve.recv()
            for request in conn:
                request.reply(vanilla.http.Status(404), {}, '')

        uri = 'http://localhost:%s' % serve.port
        response = h.http.connect(uri).get('/').recv()
        assert response.status.code == 404
        h.stop()

    def test_overlap(self):
        h = vanilla.Hub()

        serve = h.http.listen()

        @h.spawn
        def _():
            conn = serve.recv()
            for request in conn:
                t = request.path[1:]
                h.sleep(int(t))
                request.reply(vanilla.http.Status(200), {}, t)

        uri = 'http://localhost:%s' % serve.port
        conn = h.http.connect(uri)

        q = h.queue(10)

        def go(t):
            r = conn.get('/'+str(t)).recv()
            q.send(int(r.consume()))

        h.spawn(go, 50)
        h.spawn(go, 20)

        assert q.recv() == 50
        assert q.recv() == 20
        h.stop()

    def test_basic_auth(self):
        h = vanilla.Hub()

        serve = h.http.listen()

        @h.spawn
        def _():
            conn = serve.recv()
            for request in conn:
                request.reply(
                    vanilla.http.Status(200),
                    {},
                    request.headers['Authorization'])

        uri = 'http://localhost:%s' % serve.port
        conn = h.http.connect(uri)

        response = conn.get('/', auth=('foo', 'bar'))
        response = response.recv()
        assert response.consume() == 'Basic Zm9vOmJhcg=='

    def test_connection_lost(self):
        h = vanilla.Hub()

        serve = h.http.listen()

        @h.spawn
        def _():
            conn = serve.recv()
            for request in conn:
                conn.socket.close()

        uri = 'http://localhost:%s' % serve.port
        conn = h.http.connect(uri)

        response = conn.get('/')
        pytest.raises(vanilla.ConnectionLost, response.recv)
        h.stop()


class TestWebsocket(object):
    def test_websocket(self):
        h = vanilla.Hub()

        serve = h.http.listen()

        @h.spawn
        def _():
            conn = serve.recv()
            request = conn.recv()
            ws = request.upgrade()
            for item in ws.recver:
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
        h.stop()

    def test_websocket_end(self):
        h = vanilla.Hub()

        serve = h.http.listen()

        @h.spawn
        def _():
            conn = serve.recv()
            request = conn.recv()
            ws = request.upgrade()
            ws.recv()
            ws.close()

        uri = 'ws://localhost:%s' % serve.port
        ws = h.http.connect(uri).websocket('/')
        ws.send('1')
        pytest.raises(vanilla.Closed, ws.recv)
        h.stop()
