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
    assert took < 0.0003

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


def test_WebsocketClient():
    from vanilla import Websocket

    h = vanilla.Hub()

    mask = os.urandom(4)
    message = 'Hi Toby'
    assert Websocket.mask(mask, Websocket.mask(mask, message)) == message

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
