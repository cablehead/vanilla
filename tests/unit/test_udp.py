import vanilla


def test_udp():
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
