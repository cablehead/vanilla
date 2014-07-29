import time
import os
import gc

import pytest

import vanilla


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

    assert 0.003 - s.timeout() < 0.0005
    assert len(s) == 4

    s.remove(item3)
    assert 0.003 - s.timeout() < 0.0005
    assert len(s) == 3

    assert s.pop() == ('f1', ())
    assert 0.004 - s.timeout() < 0.0005
    assert len(s) == 2

    assert s.pop() == ('f2', ())
    assert 0.009 - s.timeout() < 0.0005
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


class TestPipe(object):
    def test_close_recver(self):
        h = vanilla.Hub()

        check = h.pipe()
        sender, recver = h.pipe()

        @h.spawn
        def _():
            for i in xrange(10):
                try:
                    sender.send(i)
                except vanilla.Closed:
                    break
            check.sender.send('done')

        assert recver.recv() == 0
        assert recver.recv() == 1
        recver.close()
        assert check.recver.recv() == 'done'

    def test_close_sender(self):
        h = vanilla.Hub()

        check = h.pipe()
        sender, recver = h.pipe()

        @h.spawn
        def _():
            for i in recver:
                check.sender.send(i)
            check.sender.send('done')

        sender.send(0)
        assert check.recver.recv() == 0
        sender.send(1)
        assert check.recver.recv() == 1
        sender.close()
        assert check.recver.recv() == 'done'

    def test_timeout(self):
        h = vanilla.Hub()

        sender, recver = h.pipe()
        check_sender, check_recver = h.pipe()

        pytest.raises(vanilla.Timeout, sender.send, 12, timeout=0)
        pytest.raises(vanilla.Timeout, recver.recv, timeout=0)
        pytest.raises(vanilla.Timeout, sender.send, 12, timeout=0)

        @h.spawn
        def _():
            h.sleep(20)
            check_sender.send(recver.recv())

        pytest.raises(vanilla.Timeout, sender.send, 12, timeout=10)
        sender.send(12, timeout=20)
        assert check_recver.recv() == 12

        @h.spawn
        def _():
            h.sleep(20)
            sender.send(12)

        pytest.raises(vanilla.Timeout, recver.recv, timeout=10)
        assert recver.recv(timeout=20) == 12

    def test_select(self):
        h = vanilla.Hub()

        s1, r1 = h.pipe()
        s2, r2 = h.pipe()
        check_s, check_r = h.pipe()

        @h.spawn
        def _():
            check_s.send(r1.recv())

        @h.spawn
        def _():
            s2.send(10)
            check_s.send('done')

        ch, item = h.select([s1, r2])
        assert ch == s1
        s1.send(20)

        ch, item = h.select([s1, r2])
        assert ch == r2
        assert item == 10

        assert check_r.recv() == 20
        assert check_r.recv() == 'done'

    def test_select_timeout(self):
        h = vanilla.Hub()

        s1, r1 = h.pipe()
        s2, r2 = h.pipe()
        check_s, check_r = h.pipe()

        pytest.raises(vanilla.Timeout, h.select, [s1, r2], timeout=0)

        @h.spawn
        def _():
            h.sleep(20)
            check_s.send(r1.recv())

        pytest.raises(vanilla.Timeout, h.select, [s1, r2], timeout=10)

        ch, item = h.select([s1, r2], timeout=20)
        assert ch == s1
        s1.send(20)
        assert check_r.recv() == 20

        @h.spawn
        def _():
            h.sleep(20)
            s2.send(10)
            check_s.send('done')

        pytest.raises(vanilla.Timeout, h.select, [s1, r2], timeout=10)

        ch, item = h.select([s1, r2], timeout=20)
        assert ch == r2
        assert item == 10
        assert check_r.recv() == 'done'

    def test_abandoned_sender(self):
        h = vanilla.Hub()

        check_sender, check_recver = h.pipe()

        # test abondoned after pause
        sender, recver = h.pipe()

        @h.spawn
        def _():
            pytest.raises(vanilla.Abandoned, sender.send, 10)
            check_sender.send('done')

        # sleep so the spawn runs and the send pauses
        h.sleep(1)
        del recver
        gc.collect()
        assert check_recver.recv() == 'done'

        # test abondoned before pause
        sender, recver = h.pipe()

        @h.spawn
        def _():
            pytest.raises(vanilla.Abandoned, sender.send, 10)
            check_sender.send('done')

        del recver
        gc.collect()
        assert check_recver.recv() == 'done'

    def test_abandoned_recver(self):
        h = vanilla.Hub()

        check_sender, check_recver = h.pipe()

        # test abondoned after pause
        sender, recver = h.pipe()

        @h.spawn
        def _():
            pytest.raises(vanilla.Abandoned, recver.recv)
            check_sender.send('done')

        # sleep so the spawn runs and the recv pauses
        h.sleep(1)
        del sender
        gc.collect()
        assert check_recver.recv() == 'done'

        # test abondoned before pause
        sender, recver = h.pipe()

        @h.spawn
        def _():
            pytest.raises(vanilla.Abandoned, recver.recv)
            check_sender.send('done')

        del sender
        gc.collect()
        assert check_recver.recv() == 'done'

    def test_producer(self):
        h = vanilla.Hub()

        @h.producer
        def counter(sender):
            for i in xrange(10):
                sender.send(i)

        assert counter.recv() == 0
        h.sleep(10)
        assert counter.recv() == 1

    def test_pulse(self):
        h = vanilla.Hub()

        trigger = h.pulse(20)
        pytest.raises(vanilla.Timeout, trigger.recv, timeout=0)

        h.sleep(20)
        assert trigger.recv(timeout=0)
        pytest.raises(vanilla.Timeout, trigger.recv, timeout=0)

        h.sleep(20)
        assert trigger.recv(timeout=0)
        pytest.raises(vanilla.Timeout, trigger.recv, timeout=0)

        # TODO: test abandoned


class TestBroadcast(object):
    def test_broadcast(self):
        # TODO:
        return
        print
        print
        h = vanilla.Hub()

        check = h.pipe()
        b = h.broadcast()

        print
        print

        def subscriber(name):
            print "START", name
            s = b.subscribe()
            for item in s:
                print "ITEM", item
                check.sender.send((name, item))

        h.spawn(subscriber, 's1')
        h.spawn(subscriber, 's2')
        h.sleep(1)

        b.send(1)
        print check.recver.recv()
        return
        print check.recver.recv()


class TestDescriptor(object):
    def test_recv_bytes(self):
        h = vanilla.Hub()
        r, w = os.pipe()

        r = h.poll.fileno(r)
        w = h.poll.fileno(w)

        w.send('123')
        assert r.recv_bytes(2) == '12'

        h.spawn_later(10, w.send, '2')
        assert r.recv_bytes(2) == '32'

    def test_recv_partition(self):
        h = vanilla.Hub()
        r, w = os.pipe()

        r = h.poll.fileno(r)
        w = h.poll.fileno(w)

        w.send('12\r\n3')
        assert r.recv_partition('\r\n') == '12'

        h.spawn_later(10, w.send, '2\r\n')
        assert r.recv_partition('\r\n') == '32'

    def test_close_read(self):
        # TODO
        return
        import logging
        logging.basicConfig()
        print
        print
        print "---"
        h = vanilla.Hub()
        r, w = os.pipe()

        r = h.poll.fileno(r)
        w = h.poll.fileno(w)

        w.send('123')
        assert r.recv_bytes(2) == '12'

        print "closing"
        os.close(r.conn.fileno())
        w.send('2')
        print "stopped here"
        w.send('3')

        print "yes"
        print "1"
        w.send('2')

        print "2"

        h.sleep(100)


class TestTCP(object):
    def test_tcp(self):
        h = vanilla.Hub()

        @h.tcp.listen()
        def server(conn):
            conn.send(' '.join([conn.recv()]*2))

        client = h.tcp.connect(server.port)
        client.send('Toby')
        assert client.recv() == 'Toby Toby'


class TestHTTP(object):
    def test_get_body(self):
        h = vanilla.Hub()

        @h.http.listen()
        def serve(request, response):
            return request.path

        uri = 'http://localhost:%s' % serve.port
        conn = h.http.connect(uri)

        response = conn.get('/').recv()
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

        import gc
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
        # TODO:
        return
        message = 'x' * 125
        ws.send(message)
        assert h.select([ws]) == (ws, message)
