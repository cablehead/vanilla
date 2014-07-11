import json
import time
import os


import vanilla


def test_HTTPClient():
    # TODO: Just using httpbin until the HTTP Server side of Vanilla is cleaned
    # up. There should be an integration suite that could still use httpbin.
    h = vanilla.Hub()

    conn = h.http.connect('http://httpbin.org')

    get1 = conn.get('/get', params={'foo': 'bar'})
    drip = conn.get('/drip', params={'numbytes': 3, 'duration': 3, 'delay': 1})
    get2 = conn.get('/get', params={'foo': 'bar2'})

    response = get1.recv()
    assert response.status.code == 200
    assert json.loads(response.consume())['args'] == {'foo': 'bar'}

    # assert the first payload from drip takes roughly a second
    start = time.time()
    response = drip.recv()
    took, start = time.time() - start, time.time()
    assert 1.5 > took > 1
    assert response.status.code == 200

    # response should be chunked
    assert response.headers['transfer-encoding'] == 'chunked'

    # the first chunk should come immediately
    assert response.body.recv() == '*'
    took, start = time.time() - start, time.time()
    assert took < 0.005

    # check remaining chunks come every second
    for item in response.body.recv():
        took, start = time.time() - start, time.time()
        assert item == '*'
        assert 1.4 > took > .8

    response = get2.recv()
    assert response.status.code == 200
    assert json.loads(response.consume())['args'] == {'foo': 'bar2'}


def test_WebSocketClient():
    from vanilla import WebSocket

    h = vanilla.Hub()

    mask = os.urandom(4)
    message = 'Hi Toby'
    assert WebSocket.mask(mask, WebSocket.mask(mask, message)) == message

    conn = h.http.connect('ws://echo.websocket.org')
    ws = conn.websocket('/')

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
