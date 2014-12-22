# Organ pipe arrangement of imports; because Guido likes it

import collections
import functools
import importlib
import urlparse
import hashlib
import logging
import urllib
import struct
import signal
import socket
import base64
import heapq
import uuid
import time
import ssl
import os


from greenlet import getcurrent
from greenlet import greenlet

import vanilla.exception
import vanilla.message
import vanilla.poll


__version__ = '0.0.5'


log = logging.getLogger(__name__)


class lazy(object):
    def __init__(self, f):
        self.f = f

    def __get__(self, ob, type_=None):
        value = self.f(ob)
        setattr(ob, self.f.__name__, value)
        return value


class Scheduler(object):
    Item = collections.namedtuple('Item', ['due', 'action', 'args'])

    def __init__(self):
        self.count = 0
        self.queue = []
        self.removed = {}

    def add(self, delay, action, *args):
        due = time.time() + (delay / 1000.0)
        item = self.Item(due, action, args)
        heapq.heappush(self.queue, item)
        self.count += 1
        return item

    def __len__(self):
        return self.count

    def remove(self, item):
        self.removed[item] = True
        self.count -= 1

    def prune(self):
        while True:
            if self.queue[0] not in self.removed:
                break
            item = heapq.heappop(self.queue)
            del self.removed[item]

    def timeout(self):
        self.prune()
        return self.queue[0].due - time.time()

    def pop(self):
        self.prune()
        item = heapq.heappop(self.queue)
        self.count -= 1
        return item.action, item.args


class Hub(object):
    """
    A Vanilla Hub is a handle to a self contained world of interwoven
    coroutines. It includes an event loop which is responsibile for scheduling
    which green thread should have context. Unlike most asynchronous libraries
    this Hub is explicit and must be passed to coroutines that need to interact
    with it. This is particularly nice for testing, as it makes it clear what's
    going on, and other tests can't inadvertently effect each other.
    """
    def __init__(self):
        self.log = logging.getLogger('%s.%s' % (__name__, self.__class__))

        self.ready = collections.deque()
        self.scheduled = Scheduler()

        self.stopped = self.value()

        self.registered = {}

        self.poll = vanilla.poll.Poll()

        self.signal = Signal(self)
        self.tcp = TCP(self)
        self.http = HTTP(self)

        self.loop = greenlet(self.main)

    def __getattr__(self, name):
        # facilitates dynamic plugin look up
        try:
            package = '.'.join(__name__.split('.')[:-1])
            module = importlib.import_module('.'+name, package=package)
            plugin = module.__plugin__(self)
            setattr(self, name, plugin)
            return plugin
        except Exception, e:
            log.exception(e)
            raise AttributeError(
                "'Hub' object has no attribute '{name}'\n"
                "You may be trying to use a plugin named vanilla.{name}. "
                "If you are, you still need to install it".format(
                    name=name))

    def pipe(self):
        """
        Returns a `Pipe`_ `Pair`_.
        """
        return vanilla.message.Pipe(self)

    def producer(self, f):
        """
        Convenience to create a `Pipe`_. *f* is a callable that takes the
        `Sender`_ end of this Pipe and the corresponding `Recver`_ is
        returned::

            def counter(sender):
                i = 0
                while True:
                    i += 1
                    sender.send(i)

            recver = h.producer(counter)

            recver.recv() # returns 1
            recver.recv() # returns 2
        """
        sender, recver = self.pipe()
        self.spawn(f, sender)
        return recver

    def consumer(self, f):
        # TODO: this isn't symmetric with producer. need to rethink
        # TODO: don't form a closure
        # TODO: test
        sender, recver = self.pipe()

        @self.spawn
        def _():
            for item in recver:
                f(item)
        return sender

    def pulse(self, ms, item=True):
        """
        Convenience to create a `Pipe`_ that will have *item* sent on it every
        *ms* milliseconds. The `Recver`_ end of the Pipe is returned.

        Note that since sends to a Pipe block until the Recver is ready, the
        pulses will be throttled if the Recver is unable to keep up::

            recver = h.pulse(500)

            for _ in recver:
                log.info('hello') # logs 'hello' every half a second
        """
        @self.producer
        def _(sender):
            while True:
                try:
                    self.sleep(ms)
                except vanilla.exception.Halt:
                    break
                sender.send(item)
            sender.close()
        return _

    def trigger(self, f):
        def consume(recver, f):
            for item in recver:
                f()
        sender, recver = self.pipe()
        self.spawn(consume, recver, f)
        sender.trigger = functools.partial(sender.send, True)
        return sender

    def dealer(self):
        """
        Returns a `Dealer`_ `Pair`_.
        """
        return vanilla.message.Dealer(self)

    def router(self):
        """
        Returns a `Router`_ `Pair`_.
        """
        return vanilla.message.Router(self)

    def queue(self, size):
        """
        Returns a `Queue`_ `Pair`_.
        """
        return vanilla.message.Queue(self, size)

    def channel(self, size=-1):
        """
        ::

            send --\    +---------+  /--> recv
                    +-> | Channel | -+
            send --/    +---------+  \--> recv

        A Channel can have many senders and many recvers. By default it is
        unbuffered, but you can create buffered Channels by specifying a size.
        They're structurally equivalent to channels in Go. It's implementation
        is *literally* a `Router`_ piped to a `Dealer`_, with an optional
        `Queue`_ in between.
        """
        sender, recver = self.router()
        if size > 0:
            recver = recver.pipe(self.queue(size))
        return vanilla.message.Pair(sender, recver.pipe(self.dealer()))

    def serialize(self, f):
        """
        Decorator to serialize access to a callable *f*
        """
        s = self.router()

        @self.spawn
        def _():
            for f, a, kw, r in s.recver:
                try:
                    r.send(f(*a, **kw))
                except Exception, e:
                    r.send(e)

        def _(*a, **kw):
            r = self.pipe()
            s.send((f, a, kw, r))
            return r.recv()

        return _

    def broadcast(self):
        return vanilla.message.Broadcast(self)

    def gate(self, state=False):
        return vanilla.message.Gate(self, state=state)

    def value(self):
        return vanilla.message.Value(self)

    def select(self, ends, timeout=-1):
        """
        An end is either a `Sender`_ or a `Recver`_. select takes a list of
        *ends* and blocks until *one* of them is ready. The select will block
        either forever, or until the optional *timeout* is reached. *timeout*
        is in milliseconds.

        It returns of tuple of (*end*, *value*) where *end* is the end that has
        become ready. If the *end* is a `Recver`_, then it will have already
        been *recv*'d on which will be available as *value*. For `Sender`_'s
        however the sender is still in a ready state waiting for a *send* and
        *value* is None.

        For example, the following is an appliance that takes an upstream
        `Recver`_ and a downstream `Sender`_. Sending to its upstream will
        alter it's current state. This state can be read at anytime by
        receiving on its downstream::

            def state(h, upstream, downstream):
                current = None
                while True:
                    end, value = h.select([upstream, downstream])
                    if end == upstream:
                        current = value
                    elif end == downstream:
                        end.send(current)
        """
        for end in ends:
            if end.ready:
                return end, isinstance(
                    end, vanilla.message.Recver) and end.recv() or None

        for end in ends:
            end.select()

        try:
            fired, item = self.pause(timeout=timeout)
        finally:
            for end in ends:
                end.unselect()

        return fired, item

    def pause(self, timeout=-1):
        if timeout > -1:
            item = self.scheduled.add(
                timeout,
                getcurrent(),
                vanilla.exception.Timeout('timeout: %s' % timeout))

        assert getcurrent() != self.loop, "cannot pause the main loop"

        resume = None
        try:
            resume = self.loop.switch()
        finally:
            if timeout > -1:
                if isinstance(resume, vanilla.exception.Timeout):
                    raise resume
                # since we didn't timeout, remove ourselves from scheduled
                self.scheduled.remove(item)

        # TODO: rework Value's is set test to be more natural
        if self.stopped.ready:
            raise vanilla.exception.Stop(
                'Hub stopped while we were paused. There must be a deadlock.')

        return resume

    def switch_to(self, target, *a):
        self.ready.append((getcurrent(), ()))
        return target.switch(*a)

    def throw_to(self, target, *a):
        self.ready.append((getcurrent(), ()))
        """
        if len(a) == 1 and isinstance(a[0], preserve_exception):
            return target.throw(a[0].typ, a[0].val, a[0].tb)
        """
        return target.throw(*a)

    def spawn(self, f, *a):
        """
        Schedules a new green thread to be created to run *f(\*a)* on the next
        available tick::

            def echo(pipe, s):
                pipe.send(s)

            p = h.pipe()
            h.spawn(echo, p, 'hi')
            p.recv() # returns 'hi'
        """
        self.ready.append((f, a))

    def spawn_later(self, ms, f, *a):
        """
        Spawns a callable on a new green thread, scheduled for *ms*
        milliseconds in the future::

            def echo(pipe, s):
                pipe.send(s)

            p = h.pipe()
            h.spawn_later(50, echo, p, 'hi')
            p.recv() # returns 'hi' after 50ms
        """
        self.scheduled.add(ms, f, *a)

    def sleep(self, ms=1):
        """
        Pauses the current green thread for *ms* milliseconds::

            p = h.pipe()

            @h.spawn
            def _():
                p.send('1')
                h.sleep(50)
                p.send('2')

            p.recv() # returns '1'
            p.recv() # returns '2' after 50 ms
        """
        self.scheduled.add(ms, getcurrent())
        self.loop.switch()

    def register(self, fd, *masks):
        ret = []
        self.registered[fd] = {}
        for mask in masks:
            sender, recver = self.pipe()
            self.registered[fd][mask] = sender
            ret.append(recver)
        self.poll.register(fd, *masks)
        if len(ret) == 1:
            return ret[0]
        return ret

    def unregister(self, fd):
        if fd in self.registered:
            masks = self.registered.pop(fd)
            try:
                self.poll.unregister(fd, *(masks.keys()))
            except:
                pass
            for mask in masks:
                masks[mask].close()

    def stop(self):
        self.sleep(1)

        for masks in self.registered.values():
            for sender in masks.values():
                sender.send(vanilla.exception.Stop('stop'))

        while self.scheduled:
            task, a = self.scheduled.pop()
            self.throw_to(task, vanilla.exception.Stop('stop'))

        try:
            self.stopped.recv()
        except vanilla.exception.Halt:
            return

    def stop_on_term(self):
        self.signal.subscribe(signal.SIGINT, signal.SIGTERM).recv()
        self.stop()

    def run_task(self, task, *a):
        try:
            if isinstance(task, greenlet):
                task.switch(*a)
            else:
                greenlet(task).switch(*a)
        except Exception, e:
            self.log.warn('Exception leaked back to main loop', exc_info=e)

    def main(self):
        """
        Scheduler steps:
            - run ready until exhaustion

            - if there's something scheduled
                - run overdue scheduled immediately
                - or if there's nothing registered, sleep until next scheduled
                  and then go back to ready

            - if there's nothing registered and nothing scheduled, we've
              deadlocked, so stopped

            - poll on registered, with timeout of next scheduled, if something
              is scheduled
        """

        while True:
            while self.ready:
                task, a = self.ready.popleft()
                self.run_task(task, *a)

            if self.scheduled:
                timeout = self.scheduled.timeout()
                # run overdue scheduled immediately
                if timeout < 0:
                    task, a = self.scheduled.pop()
                    self.run_task(task, *a)
                    continue

                # if nothing registered, just sleep until next scheduled
                if not self.registered:
                    time.sleep(timeout)
                    task, a = self.scheduled.pop()
                    self.run_task(task, *a)
                    continue
            else:
                timeout = -1

            # TODO: add better handling for deadlock
            if not self.registered:
                self.stopped.send(True)
                return

            # run poll
            events = None
            while True:
                try:
                    events = self.poll.poll(timeout=timeout)
                    break
                # ignore IOError from signal interrupts
                except IOError:
                    continue

            if not events:
                # timeout
                task, a = self.scheduled.pop()
                self.run_task(task, *a)

            else:
                for fd, mask in events:
                    if fd in self.registered:
                        masks = self.registered[fd]
                        if mask == vanilla.poll.POLLERR:
                            for sender in masks.values():
                                sender.close()
                        else:
                            masks[mask].send(True)


class Signal(object):
    def __init__(self, hub):
        self.hub = hub
        self.fd_r = None
        self.fd_w = None
        self.mapper = {}

    def start(self):
        pipe_r, pipe_w = C.pipe()
        self.fd_r = self.hub.poll.fileno(pipe_r)
        self.fd_w = self.hub.poll.fileno(pipe_w)

        @self.hub.spawn
        def _():
            while True:
                try:
                    data = self.fd_r.read()
                # TODO: cleanup shutdown
                except vanilla.exception.Halt:
                    break
                # TODO: add protocol to read byte at a time
                assert len(data) == 1
                sig = ord(data)
                self.mapper[sig].send(sig)

    def capture(self, sig):
        if not self.fd_r:
            self.start()

        def handler(sig, frame):
            self.fd_w.write(chr(sig))

        signal.signal(sig, handler)

    def subscribe(self, *signals):
        router = self.hub.router()

        for sig in signals:
            if sig not in self.mapper:
                self.capture(sig)
                self.mapper[sig] = self.hub.broadcast()
            self.mapper[sig].subscribe().pipe(router)

        return router.recver


class protocols(object):
    @staticmethod
    def length_prefix(conn):
        h = conn.hub

        def sender(message):
            return struct.pack('<I', len(message)) + message

        def recver(upstream, downstream):
            def recvn(recver, received, n):
                while True:
                    if len(received) >= n:
                        return received[:n], received[n:]
                    received += recver.recv()

            received = ''
            while True:
                prefix, received = recvn(upstream, received, 4)
                size, = struct.unpack('<I', prefix)
                message, received = recvn(upstream, received, size)
                downstream.send(message)

        conn.writer = h.pipe().map(sender).pipe(conn.writer)
        conn.reader = conn.reader.pipe(recver)
        return conn

    @staticmethod
    def map(conn, encode, decode):
        h = conn.hub
        conn.writer = h.pipe().map(encode).pipe(conn.writer)
        conn.reader = conn.reader.map(decode)
        return conn


class TCP(object):
    def __init__(self, hub):
        self.hub = hub

    def listen(self, port=0, host='127.0.0.1', serve=None):
        if serve:
            return TCPListener(self.hub, host, port, serve)
        return functools.partial(TCPListener, self.hub, host, port)

    def connect(self, port, host='127.0.0.1'):
        conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        # TODO: this shouldn't block on the connect
        conn.connect((host, port))
        return self.hub.poll.socket(conn)


class TCPListener(object):
    def __init__(self, hub, host, port, serve):
        self.hub = hub

        self.sock = s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((host, port))
        s.listen(socket.SOMAXCONN)
        s.setblocking(0)

        self.port = s.getsockname()[1]
        self.serve = serve

        hub.spawn(self.accept)

    def accept(self):
        ready = self.hub.register(self.sock.fileno(), C.POLLIN)
        while True:
            try:
                ready.recv()
            except vanilla.exception.Halt:
                self.hub.unregister(self.sock.fileno())
                self.sock.close()
                return
            conn, host = self.sock.accept()
            conn = self.hub.poll.socket(conn)
            self.hub.spawn(self.serve, conn)


# HTTP #####################################################################


HTTP_VERSION = 'HTTP/1.1'


class HTTP(object):
    def __init__(self, hub):
        self.hub = hub

    def connect(self, url):
        return HTTPClient(self.hub, url)

    # TODO: hacking in convenience for example, still need to add test
    # TODO: ensure connection is closed after the get is done
    def get(self, uri, params=None, headers=None):
        parsed = urlparse.urlsplit(uri)
        conn = self.connect('%s://%s' % (parsed.scheme, parsed.netloc))
        return conn.get(parsed.path, params=params, headers=headers)

    def listen(
            self,
            port=0,
            host='127.0.0.1',
            serve=None,
            request_timeout=20000):

        def launch(serve):
            @self.hub.tcp.listen(host=host, port=port)
            def server(socket):
                HTTPServer(self.hub, socket, request_timeout, serve)
            return server

        if serve:
            return launch(serve)
        return launch


class Headers(object):
    Value = collections.namedtuple('Value', ['key', 'value'])

    def __init__(self):
        self.store = {}

    def __setitem__(self, key, value):
        self.store[key.lower()] = self.Value(key, value)

    def __contains__(self, key):
        return key.lower() in self.store

    def __getitem__(self, key):
        return self.store[key.lower()].value

    def __repr__(self):
        return repr(dict(self.store.itervalues()))

    def get(self, key, default=None):
        try:
            return self[key]
        except KeyError:
            return default


class HTTPSocket(object):

    def read_headers(self):
        headers = Headers()
        while True:
            line = self.socket.read_line()
            if not line:
                break
            k, v = line.split(': ', 1)
            headers[k] = v.strip()
        return headers

    def write_headers(self, headers):
        headers = '\r\n'.join(
            '%s: %s' % (k, v) for k, v in headers.iteritems())
        self.socket.write(headers+'\r\n'+'\r\n')

    def read_chunk(self):
        length = int(self.socket.read_line(), 16)
        if length:
            chunk = self.socket.read_bytes(length)
        else:
            chunk = ''
        assert self.socket.read_bytes(2) == '\r\n'
        return chunk

    def write_chunk(self, chunk):
        self.socket.write('%s\r\n%s\r\n' % (hex(len(chunk))[2:], chunk))


class HTTPClient(HTTPSocket):

    Status = collections.namedtuple('Status', ['version', 'code', 'message'])

    class Response(object):
        def __init__(self, status, headers, body):
            self.status = status
            self.headers = headers
            self.body = body

        def consume(self):
            return ''.join(self.body)

        def __repr__(self):
            return 'HTTPClient.Response(status=%r)' % (self.status,)

    def __init__(self, hub, url):
        self.hub = hub

        parsed = urlparse.urlsplit(url)
        assert parsed.query == ''
        assert parsed.fragment == ''

        default_port = 443 if parsed.scheme == 'https' else 80
        host, port = urllib.splitnport(parsed.netloc, default_port)

        self.socket = self.hub.tcp.connect(host=host, port=port)

        # TODO: this shouldn't block on the SSL handshake
        if parsed.scheme == 'https':
            self.socket.d.conn = ssl.wrap_socket(self.socket.d.conn)
            self.socket.d.conn.setblocking(0)

        self.socket.line_break = '\r\n'

        self.agent = 'vanilla/%s' % __version__

        self.default_headers = dict([
            ('Accept', '*/*'),
            ('User-Agent', self.agent),
            ('Host', parsed.netloc), ])

        # TODO: fix API
        self.requests = self.hub.router().pipe(self.hub.queue(10))
        self.requests.pipe(self.hub.consumer(self.writer))

        self.responses = self.hub.router().pipe(self.hub.queue(10))
        self.responses.pipe(self.hub.consumer(self.reader))

    def reader(self, response):
        try:
            version, code, message = self.socket.read_line().split(' ', 2)
        except vanilla.exception.Halt:
            # TODO: could we offer the ability to auto-reconnect?
            try:
                response.send(vanilla.exception.ConnectionLost())
            except vanilla.exception.Abandoned:
                # TODO: super need to think this through
                pass
            return

        code = int(code)
        status = self.Status(version, code, message)
        # TODO:
        # if status.code == 408:

        headers = self.read_headers()
        sender, recver = self.hub.pipe()

        response.send(self.Response(status, headers, recver))

        if headers.get('Connection') == 'Upgrade':
            sender.close()
            return

        try:
            if headers.get('transfer-encoding') == 'chunked':
                while True:
                    chunk = self.read_chunk()
                    if not chunk:
                        break
                    sender.send(chunk)
            else:
                # TODO:
                # http://www.w3.org/Protocols/rfc2616/rfc2616-sec4.html#sec4.4
                body = self.socket.read_bytes(int(headers['content-length']))
                sender.send(body)
        except vanilla.exception.Halt:
            # TODO: could we offer the ability to auto-reconnect?
            sender.send(vanilla.exception.ConnectionLost())

        sender.close()

    def request(
            self,
            method,
            path='/',
            params=None,
            headers=None,
            data=None):

        self.requests.send((method, path, params, headers, data))
        sender, recver = self.hub.pipe()
        self.responses.send(sender)
        return recver

    def writer(self, request):
        method, path, params, headers, data = request

        request_headers = {}
        request_headers.update(self.default_headers)
        if headers:
            request_headers.update(headers)

        if params:
            path += '?' + urllib.urlencode(params)

        request = '%s %s %s\r\n' % (method, path, HTTP_VERSION)
        self.socket.write(request)

        # TODO: handle chunked transfers
        if data is not None:
            request_headers['Content-Length'] = len(data)
        self.write_headers(request_headers)

        # TODO: handle chunked transfers
        if data is not None:
            self.socket.write(data)

    def get(self, path='/', params=None, headers=None, auth=None):
        if auth:
            if not headers:
                headers = {}
            headers['Authorization'] = \
                'Basic ' + base64.b64encode('%s:%s' % auth)
        return self.request('GET', path, params, headers, None)

    def post(self, path='/', params=None, headers=None, data=''):
        return self.request('POST', path, params, headers, data)

    def put(self, path='/', params=None, headers=None, data=''):
        return self.request('PUT', path, params, headers, data)

    def delete(self, path='/', params=None, headers=None):
        return self.request('DELETE', path, params, headers, None)

    def websocket(self, path='/', params=None, headers=None):
        key = base64.b64encode(uuid.uuid4().bytes)

        headers = headers or {}
        headers.update({
            'Upgrade': 'WebSocket',
            'Connection': 'Upgrade',
            'Sec-WebSocket-Key': key,
            'Sec-WebSocket-Version': 13, })

        response = self.request('GET', path, params, headers, None).recv()
        assert response.status.code == 101
        assert response.headers['Upgrade'].lower() == 'websocket'
        assert response.headers['Sec-WebSocket-Accept'] == \
            WebSocket.accept_key(key)

        return WebSocket(self.hub, self.socket)


class HTTPServer(HTTPSocket):
    Request = collections.namedtuple(
        'Request', ['method', 'path', 'version', 'headers'])

    class Request(Request):
        def consume(self):
            return self.body

    class Response(object):
        """
        manages the state of a HTTP Server Response
        """
        class HTTPStatus(Exception):
            pass

        class HTTP404(HTTPStatus):
            code = 404
            message = 'Not Found'

        def __init__(self, server, request, sender):
            self.server = server
            self.request = request
            self.sender = sender

            self.status = (200, 'OK')
            self.headers = {}

            self.is_started = False
            self.is_upgraded = False

        def start(self):
            assert not self.is_started
            self.is_started = True
            self.sender.send(self.status)
            self.sender.send(self.headers)

        def send(self, data):
            if not self.is_started:
                self.headers['Transfer-Encoding'] = 'chunked'
                self.start()
            self.sender.send(data)

        def end(self, data):
            if not self.is_started:
                self.headers['Content-Length'] = len(data)
                self.start()
                self.sender.send(data or '')
            else:
                if data:
                    self.sender.send(data)
            self.sender.close()

        def upgrade(self):
            # TODO: the connection header can be a list of tokens, this should
            # be handled more comprehensively
            connection_tokens = [
                x.strip().lower()
                for x in self.request.headers['Connection'].split(',')]
            assert 'upgrade' in connection_tokens

            assert self.request.headers['Upgrade'].lower() == 'websocket'

            key = self.request.headers['Sec-WebSocket-Key']
            accept = WebSocket.accept_key(key)

            self.status = (101, 'Switching Protocols')
            self.headers.update({
                "Upgrade": "websocket",
                "Connection": "Upgrade",
                "Sec-WebSocket-Accept": accept, })

            self.start()
            self.sender.close()
            ws = WebSocket(
                self.server.hub, self.server.socket, is_client=False)
            self.is_upgraded = ws
            return ws

    def __init__(self, hub, socket, request_timeout, serve):
        self.hub = hub

        self.socket = socket
        self.socket.timeout = request_timeout
        self.socket.line_break = '\r\n'

        self.serve = serve

        self.responses = self.hub.consumer(self.writer)

        # TODO: handle Connection: close
        # TODO: spawn a green thread this request
        # TODO: handle when this is a websocket upgrade request

        while True:
            try:
                request = self.read_request()
            except vanilla.exception.Halt:
                return

            except vanilla.exception.Timeout:
                print "Request Timeout"
                self.write_response(408, 'Request Timeout')
                self.socket.close()
                return

            sender, recver = self.hub.pipe()
            response = self.Response(self, request, sender)
            self.responses.send(recver)

            try:
                data = serve(request, response)
            except response.HTTPStatus, e:
                response.status = (e.code, e.message)
                data = e.message
            except Exception, e:
                # TODO: send 500
                raise

            if response.is_upgraded:
                response.is_upgraded.close()
                return

            response.end(data)

    def writer(self, response):
        try:
            code, message = response.recv()
            self.write_response(code, message)

            headers = response.recv()
            self.write_headers(headers)

            if headers.get('Connection') == 'Upgrade':
                return

            if headers.get('Transfer-Encoding') == 'chunked':
                for chunk in response:
                    self.write_chunk(chunk)
                self.write_chunk('')
            else:
                self.socket.write(response.recv())
        except vanilla.exception.Halt:
            # TODO: should this log as a http access log line?
            log.error('HTTP Response: connection lost')

    def read_request(self, timeout=None):
        method, path, version = self.socket.read_line().split(' ', 2)
        headers = self.read_headers()
        request = self.Request(method, path, version, headers)
        # TODO: handle chunked transfers
        length = int(headers.get('content-length', 0))
        request.body = self.socket.read_bytes(length)
        return request

    def write_response(self, code, message):
        self.socket.write('HTTP/1.1 %s %s\r\n' % (code, message))


class WebSocket(object):
    MASK = FIN = 0b10000000
    RSV = 0b01110000
    OP = 0b00001111
    CONTROL = 0b00001000
    PAYLOAD = 0b01111111

    OP_TEXT = 0x1
    OP_BIN = 0x2
    OP_CLOSE = 0x8
    OP_PING = 0x9
    OP_PONG = 0xA

    SANITY = 1024**3  # limit fragments to 1GB

    def __init__(self, hub, socket, is_client=True):
        self.hub = hub
        self.socket = socket
        self.socket.timeout = -1
        self.is_client = is_client
        self.recver = self.hub.producer(self.reader)

    @staticmethod
    def mask(mask, s):
        mask_bytes = [ord(c) for c in mask]
        return ''.join(
            chr(mask_bytes[i % 4] ^ ord(c)) for i, c in enumerate(s))

    @staticmethod
    def accept_key(key):
        value = key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
        return base64.b64encode(hashlib.sha1(value).digest())

    def reader(self, sender):
        while True:
            try:
                sender.send(self._recv())
            except vanilla.exception.Halt:
                sender.close()
                return

    def recv(self):
        return self.recver.recv()

    def _recv(self):
        b1, length, = struct.unpack('!BB', self.socket.read_bytes(2))
        assert b1 & WebSocket.FIN, "Fragmented messages not supported yet"

        if self.is_client:
            assert not length & WebSocket.MASK
        else:
            assert length & WebSocket.MASK
            length = length & WebSocket.PAYLOAD

        # TODO: support binary
        opcode = b1 & WebSocket.OP

        if opcode & WebSocket.CONTROL:
            # this is a control frame
            assert length <= 125
            if opcode == WebSocket.OP_CLOSE:
                self.socket.read_bytes(length)
                self.socket.close()
                raise vanilla.exception.Closed

        if length == 126:
            length, = struct.unpack('!H', self.socket.read_bytes(2))

        elif length == 127:
            length, = struct.unpack('!Q', self.socket.read_bytes(8))

        assert length < WebSocket.SANITY, "Frames limited to 1Gb for sanity"

        if self.is_client:
            return self.socket.read_bytes(length)

        mask = self.socket.read_bytes(4)
        return self.mask(mask, self.socket.read_bytes(length))

    def send(self, data):
        length = len(data)

        MASK = WebSocket.MASK if self.is_client else 0

        if length <= 125:
            header = struct.pack(
                '!BB',
                WebSocket.OP_TEXT | WebSocket.FIN,
                length | MASK)

        elif length <= 65535:
            header = struct.pack(
                '!BBH',
                WebSocket.OP_TEXT | WebSocket.FIN,
                126 | MASK,
                length)
        else:
            assert length < WebSocket.SANITY, \
                "Frames limited to 1Gb for sanity"
            header = struct.pack(
                '!BBQ',
                WebSocket.OP_TEXT | WebSocket.FIN,
                127 | MASK,
                length)

        if self.is_client:
            mask = os.urandom(4)
            self.socket.write(header + mask + self.mask(mask, data))
        else:
            self.socket.write(header + data)

    def close(self):
        if not self.socket.closed:
            MASK = WebSocket.MASK if self.is_client else 0
            header = struct.pack(
                '!BB',
                WebSocket.OP_CLOSE | WebSocket.FIN,
                MASK)
            self.socket.write(header)
            self.socket.close()
