import vanilla


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
