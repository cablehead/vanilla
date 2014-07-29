# Organ pipe arrangement of imports; because Guido likes it

import collections
import functools
import urlparse
import weakref
import logging
import urllib
import select
import socket
import fcntl
import heapq
import cffi
import time
import os


from greenlet import getcurrent
from greenlet import greenlet


__version__ = '0.0.1'


log = logging.getLogger(__name__)


class Timeout(Exception):
    pass


class Halt(Exception):
    pass


class Closed(Halt):
    pass


class Abandoned(Halt):
    pass


def init_C():
    ffi = cffi.FFI()

    ffi.cdef("""

    ssize_t read(int fd, void *buf, size_t count);

    int eventfd(unsigned int initval, int flags);

    #define SIG_BLOCK ...
    #define SIG_UNBLOCK ...
    #define SIG_SETMASK ...

    typedef struct { ...; } sigset_t;

    int sigprocmask(int how, const sigset_t *set, sigset_t *oldset);

    int sigemptyset(sigset_t *set);
    int sigfillset(sigset_t *set);
    int sigaddset(sigset_t *set, int signum);
    int sigdelset(sigset_t *set, int signum);
    int sigismember(const sigset_t *set, int signum);

    #define SFD_NONBLOCK ...
    #define SFD_CLOEXEC ...

    #define EAGAIN ...

    #define EPOLLIN ...
    #define EPOLLOUT ...
    #define EPOLLET ...
    #define EPOLLERR ...
    #define EPOLLHUP ...
    #define EPOLLRDHUP ...

    #define SIGALRM ...
    #define SIGINT ...
    #define SIGTERM ...
    #define SIGCHLD ...

    struct signalfd_siginfo {
        uint32_t ssi_signo;   /* Signal number */
        ...;
    };

    int signalfd(int fd, const sigset_t *mask, int flags);

    /*
        INOTIFY */

    #define IN_ACCESS ...         /* File was accessed. */
    #define IN_MODIFY ...         /* File was modified. */
    #define IN_ATTRIB ...         /* Metadata changed. */
    #define IN_CLOSE_WRITE ...    /* Writtable file was closed. */
    #define IN_CLOSE_NOWRITE ...  /* Unwrittable file closed. */
    #define IN_OPEN ...           /* File was opened. */
    #define IN_MOVED_FROM ...     /* File was moved from X. */
    #define IN_MOVED_TO ...       /* File was moved to Y. */
    #define IN_CREATE ...         /* Subfile was created. */
    #define IN_DELETE ...         /* Subfile was deleted. */
    #define IN_DELETE_SELF ...    /* Self was deleted. */
    #define IN_MOVE_SELF ...      /* Self was moved. */

    /* Events sent by the kernel. */
    #define IN_UNMOUNT ...    /* Backing fs was unmounted. */
    #define IN_Q_OVERFLOW ... /* Event queued overflowed. */
    #define IN_IGNORED ...    /* File was ignored. */

    /* Helper events. */
    #define IN_CLOSE ... /* Close. */
    #define IN_MOVE ...  /* Moves. */

    /* Special flags. */
    #define IN_ONLYDIR ...      /* Only watch the path if it is a directory. */
    #define IN_DONT_FOLLOW ...  /* Do not follow a sym link. */
    #define IN_EXCL_UNLINK ...  /* Exclude events on unlinked objects. */
    #define IN_MASK_ADD ...     /* Add to the mask of an already existing
                                   watch. */
    #define IN_ISDIR ...        /* Event occurred against dir. */
    #define IN_ONESHOT ...      /* Only send event once. */

    /* All events which a program can wait on. */
    #define IN_ALL_EVENTS ...

    #define IN_NONBLOCK ...
    #define IN_CLOEXEC ...

    int inotify_init(void);
    int inotify_init1(int flags);
    int inotify_add_watch(int fd, const char *pathname, uint32_t mask);

    /*
        PRCTL */

    #define PR_SET_PDEATHSIG ...

    int prctl(int option, unsigned long arg2, unsigned long arg3,
              unsigned long arg4, unsigned long arg5);
    """)

    C = ffi.verify("""
        #include <signal.h>
        #include <sys/signalfd.h>
        #include <sys/eventfd.h>
        #include <sys/inotify.h>
        #include <sys/epoll.h>
        #include <sys/prctl.h>
    """)

    # stash some conveniences on C
    C.ffi = ffi
    C.NULL = ffi.NULL

    def Cdot(f):
        setattr(C, f.__name__, f)

    @Cdot
    def sigset(*nums):
        s = ffi.new('sigset_t *')
        assert not C.sigemptyset(s)

        for num in nums:
            rc = C.sigaddset(s, num)
            assert not rc, "signum: %s doesn't specify a valid signal." % num
        return s

    @Cdot
    def unblock(fd):
        flags = fcntl.fcntl(fd, fcntl.F_GETFL, 0)
        flags = flags | os.O_NONBLOCK
        fcntl.fcntl(fd, fcntl.F_SETFL, flags)
        return fd

    return C


C = init_C()


Pipe = collections.namedtuple('Pipe', ['sender', 'recver'])


class Pair(object):
    __slots__ = ['hub', 'current', 'pair', 'closed']

    def __init__(self, hub):
        self.hub = hub
        self.current = None
        self.pair = None
        self.closed = False

    def on_abandoned(self, *a, **kw):
        if self.current:
            self.hub.throw_to(self.current, Abandoned)

    def pair_to(self, pair):
        self.pair = weakref.ref(pair, self.on_abandoned)

    @property
    def other(self):
        return self.pair().current

    @property
    def ready(self):
        if self.pair() is None:
            raise Abandoned
        if self.pair().closed:
            raise Closed
        return self.other is not None

    def select(self, current=None):
        assert self.current is None
        self.current = current or getcurrent()

    def unselect(self):
        assert self.current == getcurrent()
        self.current = None

    def pause(self, timeout=-1):
        self.select()
        try:
            _, ret = self.hub.pause(timeout=timeout)
        finally:
            self.unselect()
        return ret

    def close(self):
        self.closed = True
        if self.ready:
            self.hub.throw_to(self.other, Closed)


class Sender(Pair):
    def send(self, item, timeout=-1):
        # only allow one send at a time
        assert self.current is None
        if not self.ready:
            self.pause(timeout=timeout)
        return self.hub.switch_to(self.other, self.pair(), item)


class Recver(Pair):
    def recv(self, timeout=-1):
        # only allow one recv at a time
        assert self.current is None

        if self.ready:
            self.current = getcurrent()
            # switch directly, as we need to pause
            _, ret = self.other.switch(self.pair(), None)
            self.current = None
            return ret

        return self.pause(timeout=timeout)

    def __iter__(self):
        while True:
            try:
                yield self.recv()
            except Halt:
                break


class Broadcast(object):
    def __init__(self, hub):
        self.hub = hub
        self.subscribers = []

    def send(self, item):
        # TODO: should we only send to subscribers who are ready?
        # if not, how is this different to a tee?
        for subscriber in self.subscribers:
            subscriber.send(item)

    def subscribe(self):
        sender, recver = self.hub.pipe()
        self.subscribers.append(sender)
        return recver


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
    def __init__(self):
        self.log = logging.getLogger('%s.%s' % (__name__, self.__class__))

        self.ready = collections.deque()
        self.scheduled = Scheduler()

        # self.stopped = self.event()

        self.epoll = select.epoll()
        self.registered = {}

        self.poll = Poll(self)
        self.tcp = TCP(self)
        self.http = HTTP(self)

        self.loop = greenlet(self.main)

    def sender(self):
        return Sender(self)

    def recver(self):
        return Recver(self)

    def pipe(self):
        sender = self.sender()
        recver = self.recver()
        sender.pair_to(recver)
        recver.pair_to(sender)
        return Pipe(sender, recver)

    def producer(self, f):
        sender, recver = self.pipe()
        self.spawn(f, sender)
        return recver

    def pulse(self, ms, item=True):
        @self.producer
        def _(sender):
            while True:
                self.sleep(ms)
                sender.send(item)
        return _

    def consumer(self, f):
        # TODO: don't form a closure
        # TODO: test
        sender, recver = self.pipe()

        @self.spawn
        def _():
            for item in recver:
                f(item)
        return sender

    def trigger(self, f):
        # TODO: don't form a closure
        sender, recver = self.pipe()

        @self.spawn
        def _():
            for item in recver:
                f()
        return lambda: sender.send(True)

    def broadcast(self):
        return Broadcast(self)

    def select(self, pairs, timeout=-1):
        for pair in pairs:
            if pair.ready:
                return pair, isinstance(pair, Recver) and pair.recv() or None

        for pair in pairs:
            pair.select()

        try:
            fired, item = self.pause(timeout=timeout)
        finally:
            for pair in pairs:
                pair.unselect()

        return fired, item

    def pause(self, timeout=-1):
        if timeout > -1:
            item = self.scheduled.add(
                timeout, getcurrent(), Timeout('timeout: %s' % timeout))

        assert getcurrent() != self.loop, "cannot pause the main loop"
        resume = self.loop.switch()

        if timeout > -1:
            if isinstance(resume, Timeout):
                raise resume

            # since we didn't timeout, remove ourselves from scheduled
            self.scheduled.remove(item)

        """
        # TODO: clean up stopped handling here
        if self.stopped:
            raise Closed('closed')
        """

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
        self.ready.append((f, a))

    def spawn_later(self, ms, f, *a):
        self.scheduled.add(ms, f, *a)

    def sleep(self, ms=1):
        self.scheduled.add(ms, getcurrent())
        self.loop.switch()

    def register(self, fd, mask):
        # TODO: is it an issue that this will block our epoll if the sender
        # isn't ready? -- ah, we should only poll on fds that are ready to recv
        sender, recver = self.pipe()

        self.registered[fd] = sender
        self.epoll.register(fd, mask)
        return recver

    def unregister(self, fd):
        if fd in self.registered:
            try:
                self.epoll.unregister(fd)
            except:
                pass
            ch = self.registered.pop(fd)
            ch.close()

    """
    def stop(self):
        self.sleep(1)

        for fd, ch in self.registered.items():
            ch.send(Stop('stop'))

        while self.scheduled:
            task, a = self.scheduled.pop()
            self.throw_to(task, Stop('stop'))

        try:
            self.stopped.wait()
        except Closed:
            return
    """

    def stop_on_term(self):
        done = self.signal.subscribe(C.SIGINT, C.SIGTERM)
        done.recv()
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

            - epoll on registered, with timeout of next scheduled, if something
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
                self.stopped.set()
                return

            # run epoll
            events = None
            while True:
                try:
                    events = self.epoll.poll(timeout=timeout)
                    break
                # ignore IOError from signal interrupts
                except IOError:
                    continue

            if not events:
                # timeout
                task, a = self.scheduled.pop()
                self.run_task(task, *a)

            else:
                for fd, event in events:
                    if fd in self.registered:
                        # TODO: rethink this
                        if self.registered[fd].ready:
                            self.registered[fd].send((fd, event))


class Poll(object):
    def __init__(self, hub):
        self.hub = hub

    def socket(self, conn):
        return Descriptor(self.hub, conn)

    def fileno(self, fileno):
        class Adapt(object):
            def __init__(self, fd):
                self.fd = fd

            def fileno(self):
                return self.fd

            def recv(self, n):
                return os.read(self.fd, n)

            def send(self, data):
                return os.write(self.fd, data)

            def close(self):
                try:
                    os.close(self.fd)
                except OSError:
                    pass
        return Descriptor(self.hub, Adapt(fileno))


class Descriptor(object):
    FLAG_TO_HUMAN = [
        (C.EPOLLIN, 'in'),
        (C.EPOLLOUT, 'out'),
        (C.EPOLLHUP, 'hup'),
        (C.EPOLLERR, 'err'),
        (C.EPOLLET, 'et'),
        (C.EPOLLRDHUP, 'rdhup'), ]

    @staticmethod
    def humanize_mask(mask):
        s = []
        for k, v in Descriptor.FLAG_TO_HUMAN:
            if k & mask:
                s.append(v)
        return s

    def __init__(self, hub, conn):
        self.hub = hub

        C.unblock(conn.fileno())
        self.conn = conn

        self.timeout = -1
        self.line_break = '\n'

        self.events = self.hub.register(
            self.conn.fileno(),
            C.EPOLLIN | C.EPOLLOUT | C.EPOLLHUP | C.EPOLLERR | C.EPOLLET |
            C.EPOLLRDHUP)

        # TODO: if this is a read or write only file, don't set up both
        # directions
        self.recv_extra = ''
        self.recv_sender, self.recver = self.hub.pipe()
        self.sender, self.send_recver = self.hub.pipe()

        self.trigger_reader = self.hub.trigger(self.reader)

        # self.trigger_writer = self.hub.trigger(self.writer)
        self.hub.spawn(self.writer)

        self.hub.spawn(self.main)

    def upgrade(self, klass, *a, **kw):
        self.__class__ = klass
        self.init(*a, **kw)

    def recv(self):
        return self.recver.recv(timeout=self.timeout)

    def send(self, data):
        return self.sender.send(data)

    def recv_bytes(self, n):
        if n == 0:
            return ''

        received = len(self.recv_extra)
        segments = [self.recv_extra]
        while received < n:
            segment = self.recv()
            segments.append(segment)
            received += len(segment)

        # if we've received too much, break the last segment and return the
        # additional portion to pending
        overage = received - n
        if overage:
            self.recv_extra = segments[-1][-1*(overage):]
            segments[-1] = segments[-1][:-1*(overage)]
        else:
            self.recv_extra = ''

        return ''.join(segments)

    def recv_partition(self, sep):
        received = self.recv_extra
        while True:
            keep, matched, extra = received.partition(sep)
            if matched:
                self.recv_extra = extra
                return keep
            received += self.recv()

    def recv_line(self):
        return self.recv_partition(self.line_break)

    def reader(self):
        while True:
            try:
                self.recv_sender.send(self.conn.recv(4096))
            except (socket.error, OSError), e:
                if e.errno == 11:  # EAGAIN
                    break
                raise

    def writer(self):
        for data in self.send_recver:
            while True:
                try:
                    n = self.conn.send(data)
                except (socket.error, OSError), e:
                    if e.errno == 11:  # EAGAIN
                        raise
                    return
                if n == len(data):
                    break
                data = data[n:]

    def main(self):
        for fileno, event in self.events:
            if event & C.EPOLLIN:
                self.trigger_reader()

            elif event & C.EPOLLOUT:
                # self.trigger_writer()
                pass


class TCP(object):
    def __init__(self, hub):
        self.hub = hub

    def listen(self, port=0, host='127.0.0.1', serve=None):
        if serve:
            return TCPListener(self.hub, host, port, serve)
        return functools.partial(TCPListener, self.hub, host, port)

    def connect(self, port, host='127.0.0.1'):
        conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
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
        ready = self.hub.register(self.sock.fileno(), C.EPOLLIN)
        while True:
            ready.recv()
            conn, host = self.sock.accept()
            conn = self.hub.poll.socket(conn)
            self.hub.spawn(self.serve, conn)


# HTTP #####################################################################


HTTP_VERSION = 'HTTP/1.1'


class HTTP(object):
    def __init__(self, hub):
        self.hub = hub

    def connect(self, url):
        parsed = urlparse.urlsplit(url)
        assert parsed.query == ''
        assert parsed.fragment == ''
        host, port = urllib.splitnport(parsed.netloc, 80)

        conn = self.hub.tcp.connect(host=host, port=port)
        conn.upgrade(HTTPClient, parsed.netloc)
        return conn

    def listen(
            self,
            port=0,
            host='127.0.0.1',
            serve=None,
            request_timeout=20000):

        def partial(serve):
            def upgrade(conn):
                conn.upgrade(HTTPServer, request_timeout, serve)
            return self.hub.tcp.listen(host=host, port=port, serve=upgrade)

        if serve:
            return partial(serve)
        return partial


class Headers(object):
    Value = collections.namedtuple('Value', ['key', 'value'])

    def __init__(self):
        self.store = {}

    def __setitem__(self, key, value):
        self.store[key.lower()] = self.Value(key, value)

    def __getitem__(self, key):
        return self.store[key.lower()].value

    def __repr__(self):
        return repr(dict(self.store.itervalues()))

    def get(self, key, default=None):
        try:
            return self[key]
        except KeyError:
            return default


class HTTPSocket(Descriptor):
    def recv_headers(self):
        headers = Headers()
        while True:
            line = self.recv_line()
            if not line:
                break
            k, v = line.split(': ', 1)
            headers[k] = v.strip()
        return headers

    def send_headers(self, headers):
        headers = '\r\n'.join(
            '%s: %s' % (k, v) for k, v in headers.iteritems())
        self.send(headers+'\r\n'+'\r\n')


class HTTPClient(HTTPSocket):

    Status = collections.namedtuple('Status', ['version', 'code', 'message'])

    class Response(object):
        def __init__(self, status, headers, body):
            self.status = status
            self.headers = headers
            self.body = body

        def consume(self):
            return ''.join(self.body)

    def init(self, netloc):
        self.agent = 'vanilla/%s' % __version__

        self.default_headers = dict([
            ('Accept', '*/*'),
            ('User-Agent', self.agent),
            ('Host', netloc), ])

        self.line_break = '\r\n'
        self.responses = self.hub.consumer(self.reader)

    def reader(self, response):
        version, code, message = self.recv_line().split(' ', 2)
        code = int(code)
        status = self.Status(version, code, message)
        # TODO:
        # if status.code == 408:

        headers = self.recv_headers()
        sender, recver = self.hub.pipe()
        response.send(self.Response(status, headers, recver))

        if headers.get('transfer-encoding') == 'chunked':
            while True:
                chunk = self.recv_chunk()
                if not chunk:
                    break
                sender.send(chunk)
        else:
            # TODO:
            # http://www.w3.org/Protocols/rfc2616/rfc2616-sec4.html#sec4.4
            body = self.recv_bytes(int(headers['content-length']))
            sender.send(body)

        sender.close()

    def recv_chunk(self):
        length = int(self.recv_line(), 16)
        if length:
            chunk = self.recv_bytes(length)
        else:
            chunk = ''
        assert self.recv_bytes(2) == '\r\n'
        return chunk

    def request(
            self,
            method,
            path='/',
            params=None,
            headers=None,
            version=HTTP_VERSION):

        request_headers = {}
        request_headers.update(self.default_headers)
        if headers:
            request_headers.update(headers)

        if params:
            path += '?' + urllib.urlencode(params)

        request = '%s %s %s\r\n' % (method, path, version)
        self.send(request)
        self.send_headers(request_headers)

        sender, recver = self.hub.pipe()
        self.responses.send(sender)
        return recver

    def get(self, path='/', params=None, headers=None, version=HTTP_VERSION):
        return self.request('GET', path, params, headers, version)


class HTTPServer(HTTPSocket):
    Request = collections.namedtuple(
        'Request', ['method', 'path', 'version', 'headers'])

    class Response(object):
        """
        manages the state of a HTTP Server Response
        """

        class HTTPStatus(Exception):
            pass

        class HTTP404(HTTPStatus):
            code = 404
            message = 'Not Found'

        def __init__(self, sender):
            self.sender = sender

            self.status = (200, 'OK')
            self.headers = {}

            self.is_started = False
            self.is_upgraded = False

        def start(self):
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

    def init(self, request_timeout, serve):
        self.timeout = request_timeout
        self.line_break = '\r\n'
        self.responses = self.hub.consumer(self.writer)

        # TODO: handle Connection: close
        # TODO: spawn a green thread this request
        while True:
            request = self.recv_request()

            sender, recver = self.hub.pipe()
            response = self.Response(sender)
            self.responses.send(recver)

            data = serve(request, response)
            response.end(data)

    def writer(self, response):
        code, message = response.recv()
        self.send_response(code, message)

        headers = response.recv()
        self.send_headers(headers)

        if headers.get('Transfer-Encoding') == 'chunked':
            for chunk in response:
                self.send_chunk(chunk)
            self.send_chunk('')
        else:
            self.send(response.recv())

    def recv_request(self, timeout=None):
        method, path, version = self.recv_line().split(' ', 2)
        headers = self.recv_headers()
        return self.Request(method, path, version, headers)

    def send_response(self, code, message):
        self.send('HTTP/1.1 %s %s\r\n' % (code, message))

    def send_chunk(self, chunk):
        self.send('%s\r\n%s\r\n' % (hex(len(chunk))[2:], chunk))
