import vanilla


class TestTCP(object):
    def test_tcp(self):
        h = vanilla.Hub()
        server = h.tcp.listen()

        @h.spawn
        def _():
            conn = server.recv()
            message = conn.recv()
            conn.send('Echo: ' + message)

        client = h.tcp.connect(server.port)
        client.send('Toby')
        assert client.recv() == 'Echo: Toby'

        h.stop()
        assert not h.registered
