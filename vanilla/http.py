import collections
import functools
import urlparse
import logging
import hashlib
import base64
import urllib
import struct
import time
import uuid
import ssl
import os

import vanilla.exception
import vanilla.message
import vanilla.meta


HTTP_VERSION = 'HTTP/1.1'


log = logging.getLogger(__name__)


class __plugin__(object):
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

    def listen(self, port=0, host='127.0.0.1'):
        server = self.hub.tcp.listen(host=host, port=port)
        ret = server.map(
            lambda conn: HTTPServer(self.hub, conn))
        ret.port = server.port
        return ret


REASON_PHRASES = {
    100: 'CONTINUE',
    101: 'SWITCHING PROTOCOLS',
    102: 'PROCESSING',
    200: 'OK',
    201: 'CREATED',
    202: 'ACCEPTED',
    203: 'NON-AUTHORITATIVE INFORMATION',
    204: 'NO CONTENT',
    205: 'RESET CONTENT',
    206: 'PARTIAL CONTENT',
    207: 'MULTI-STATUS',
    208: 'ALREADY REPORTED',
    226: 'IM USED',
    300: 'MULTIPLE CHOICES',
    301: 'MOVED PERMANENTLY',
    302: 'FOUND',
    303: 'SEE OTHER',
    304: 'NOT MODIFIED',
    305: 'USE PROXY',
    306: 'RESERVED',
    307: 'TEMPORARY REDIRECT',
    308: 'PERMANENT REDIRECT',
    400: 'BAD REQUEST',
    401: 'UNAUTHORIZED',
    402: 'PAYMENT REQUIRED',
    403: 'FORBIDDEN',
    404: 'NOT FOUND',
    405: 'METHOD NOT ALLOWED',
    406: 'NOT ACCEPTABLE',
    407: 'PROXY AUTHENTICATION REQUIRED',
    408: 'REQUEST TIMEOUT',
    409: 'CONFLICT',
    410: 'GONE',
    411: 'LENGTH REQUIRED',
    412: 'PRECONDITION FAILED',
    413: 'REQUEST ENTITY TOO LARGE',
    414: 'REQUEST-URI TOO LONG',
    415: 'UNSUPPORTED MEDIA TYPE',
    416: 'REQUESTED RANGE NOT SATISFIABLE',
    417: 'EXPECTATION FAILED',
    418: "I'M A TEAPOT",
    422: 'UNPROCESSABLE ENTITY',
    423: 'LOCKED',
    424: 'FAILED DEPENDENCY',
    426: 'UPGRADE REQUIRED',
    428: 'PRECONDITION REQUIRED',
    429: 'TOO MANY REQUESTS',
    431: 'REQUEST HEADER FIELDS TOO LARGE',
    500: 'INTERNAL SERVER ERROR',
    501: 'NOT IMPLEMENTED',
    502: 'BAD GATEWAY',
    503: 'SERVICE UNAVAILABLE',
    504: 'GATEWAY TIMEOUT',
    505: 'HTTP VERSION NOT SUPPORTED',
    506: 'VARIANT ALSO NEGOTIATES',
    507: 'INSUFFICIENT STORAGE',
    508: 'LOOP DETECTED',
    510: 'NOT EXTENDED',
    511: 'NETWORK AUTHENTICATION REQUIRED',
}


def Status(code):
    return code, REASON_PHRASES[code]


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

    def recv_headers(self):
        headers = Headers()
        while True:
            line = self.socket.recv_line()
            if not line:
                break
            k, v = line.split(': ', 1)
            headers[k] = v.strip()
        return headers

    def send_headers(self, headers):
        headers = '\r\n'.join(
            '%s: %s' % (k, v) for k, v in headers.iteritems())
        self.socket.send(headers+'\r\n'+'\r\n')

    def recv_chunk(self):
        length = int(self.socket.recv_line(), 16)
        if length:
            chunk = self.socket.recv_n(length)
        else:
            chunk = ''
        assert self.socket.recv_n(2) == '\r\n'
        return chunk

    def send_chunk(self, chunk):
        self.socket.send('%s\r\n%s\r\n' % (hex(len(chunk))[2:], chunk))


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
            # TODO: what a mess
            conn = self.socket.sender.fd.conn
            conn = ssl.wrap_socket(conn)
            conn.setblocking(0)
            self.socket.sender.fd.conn = conn

        self.socket.recver.sep = '\r\n'

        self.agent = 'vanilla/%s' % vanilla.meta.__version__

        self.default_headers = dict([
            ('Accept', '*/*'),
            ('User-Agent', self.agent),
            ('Host', parsed.netloc), ])

        self.requests = self.hub.router().pipe(self.hub.queue(10))
        self.requests.pipe(self.hub.consumer(self.writer))

        self.responses = self.hub.router().pipe(self.hub.queue(10))
        self.responses.pipe(self.hub.consumer(self.reader))

    def reader(self, response):
        try:
            version, code, message = self.socket.recv_line().split(' ', 2)
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

        headers = self.recv_headers()
        sender, recver = self.hub.pipe()

        response.send(self.Response(status, headers, recver))

        if headers.get('Connection') == 'Upgrade':
            sender.close()
            return

        try:
            if headers.get('transfer-encoding') == 'chunked':
                while True:
                    chunk = self.recv_chunk()
                    if not chunk:
                        break
                    sender.send(chunk)
            else:
                # TODO:
                # http://www.w3.org/Protocols/rfc2616/rfc2616-sec4.html#sec4.4
                length = headers.get('content-length')
                if length is None:
                    """
                    TODO:
                    content-length isn't in header, assume body is marked by
                    connection closed
                    """
                    body = ''
                    while True:
                        try:
                            body += self.socket.recv()
                        except vanilla.exception.Closed:
                            break
                    sender.send(body)
                else:
                    body = self.socket.recv_n(int(length))
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
        self.socket.send(request)

        # TODO: handle chunked transfers
        if data is not None:

            if isinstance(data, dict):
                request_headers['Content-Type'] = \
                    'application/x-www-form-urlencoded'
                data = urllib.urlencode(data)

            request_headers['Content-Length'] = len(data)

        self.send_headers(request_headers)

        # TODO: handle chunked transfers
        if data is not None:
            self.socket.send(data)

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
    def __init__(self, hub, socket):
        self.hub = hub

        self.socket = socket
        self.socket.recver.sep = '\r\n'

        self.responses = self.hub.router()

        @self.responses.consume
        def writer(response):
            status, headers, body = response

            self.socket.send('HTTP/1.1 %s %s\r\n' % status)

            if headers.get('Connection') == 'Upgrade':
                self.send_headers(headers)
                self.responses.close()
                return

            headers.setdefault(
                'Date',
                time.strftime('%a, %d %b %Y %H:%M:%S GMT', time.gmtime()))

            # if body is a pipe, use chunked encoding
            if hasattr(body, 'recv'):
                headers['Transfer-Encoding'] = 'chunked'
                self.send_headers(headers)
                for chunk in body:
                    self.send_chunk(chunk)
                self.send_chunk('')

            # otherwise send in oneshot
            else:
                headers['Content-Length'] = len(body)
                self.send_headers(headers)
                self.socket.send(body)

    Request = collections.namedtuple(
        'Request', ['method', 'path', 'version', 'headers'])

    class Request(Request):

        @property
        def form(self):
            if self.headers.get('Content-Type') != \
                    'application/x-www-form-urlencoded':
                raise AttributeError('not a form encoded request')
            return dict(urlparse.parse_qsl(self.body))

        @property
        def form_multi(self):
            if self.headers.get('Content-Type') != \
                    'application/x-www-form-urlencoded':
                raise AttributeError('not a form encoded request')
            return urlparse.parse_qs(self.body)

        def consume(self):
            return self.body

        def reply(self, status, headers, body):
            self.server.responses.send((status, headers, body))

        def upgrade(self):
            # TODO: the connection header can be a list of tokens, this should
            # be handled more comprehensively
            connection_tokens = [
                x.strip().lower()
                for x in self.headers['Connection'].split(',')]
            assert 'upgrade' in connection_tokens

            assert self.headers['Upgrade'].lower() == 'websocket'

            key = self.headers['Sec-WebSocket-Key']
            accept = WebSocket.accept_key(key)
            headers = {
                "Upgrade": "websocket",
                "Connection": "Upgrade",
                "Sec-WebSocket-Accept": accept, }

            self.reply(Status(101), headers, None)

            return WebSocket(
                self.server.hub, self.server.socket, is_client=False)

    def recv(self, timeout=None):
        method, path, version = self.socket.recv_line().split(' ', 2)
        headers = self.recv_headers()
        request = self.Request(method, path, version, headers)
        # TODO: handle chunked transfers
        length = int(headers.get('content-length', 0))
        request.body = self.socket.recv_n(length)
        request.server = self
        return request

    # TODO: we should provide the standard Recver API
    def __iter__(self):
        while True:
            try:
                yield self.recv()
            except vanilla.exception.Halt:
                break


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

    def __new__(cls, hub, socket, is_client=True):
        sender = hub.pipe() \
            .map(functools.partial(WebSocket.send, is_client)) \
            .pipe(socket).sender

        recver = socket \
            .pipe(functools.partial(WebSocket.recv, is_client)).recver

        @recver.onclose
        def close():
            MASK = WebSocket.MASK if is_client else 0
            header = struct.pack(
                '!BB',
                WebSocket.OP_CLOSE | WebSocket.FIN,
                MASK)
            socket.send(header)
            socket.close()

        return vanilla.message.Pair(sender, recver)

    @staticmethod
    def mask(mask, s):
        mask_bytes = [ord(c) for c in mask]
        return ''.join(
            chr(mask_bytes[i % 4] ^ ord(c)) for i, c in enumerate(s))

    @staticmethod
    def accept_key(key):
        value = key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
        return base64.b64encode(hashlib.sha1(value).digest())

    @staticmethod
    def send(is_client, data):
        length = len(data)

        MASK = WebSocket.MASK if is_client else 0

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

        if is_client:
            mask = os.urandom(4)
            return header + mask + WebSocket.mask(mask, data)
        else:
            return header + data

    @staticmethod
    def recv(is_client, upstream, downstream):
        while True:
            b1, length, = struct.unpack('!BB', upstream.recv_n(2))
            assert b1 & WebSocket.FIN, "Fragmented messages not supported yet"

            if is_client:
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
                    upstream.recv_n(length)
                    upstream.close()
                    raise vanilla.exception.Closed

            if length == 126:
                length, = struct.unpack('!H', upstream.recv_n(2))

            elif length == 127:
                length, = struct.unpack('!Q', upstream.recv_n(8))

            assert length < WebSocket.SANITY, \
                "Frames limited to 1Gb for sanity"

            if is_client:
                downstream.send(upstream.recv_n(length))
            else:
                mask = upstream.recv_n(4)
                downstream.send(WebSocket.mask(mask, upstream.recv_n(length)))
