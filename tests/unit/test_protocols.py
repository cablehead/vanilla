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
