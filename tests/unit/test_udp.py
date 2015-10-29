import vanilla


def test_core():
    h = vanilla.Hub()

    serve = h.udp.listen()

    client = h.udp.create()
    client.send(('foo', ('127.0.0.1', serve.port)))

    data, addr = serve.recv()
    assert data == 'foo'
    serve.send(('Echo: ' + data, addr))

    data, addr = client.recv()
    assert data == 'Echo: foo'
    assert addr == ('127.0.0.1', serve.port)

    serve.close()
    client.close()
    assert h.registered == {}


def test_send():
    h = vanilla.Hub()

    N = 5
    serve = h.udp.listen()

    @h.spawn
    def _():
        client = h.udp.create()
        for i in xrange(N):
            if not i % 2000:
                h.sleep(1)
            client.send((str(i), ('127.0.0.1', serve.port)))

    for i in xrange(N):
        data, addr = serve.recv()
        assert int(data) == i
