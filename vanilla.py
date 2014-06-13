# Organ pipe arrangement of imports; because Guido likes it

import collections
import traceback
import functools
import urlparse
import hashlib
import logging
import urllib
import base64
import socket
import select
import struct
import heapq
import fcntl
import cffi
import uuid
import time
import sys
import os


from greenlet import getcurrent
from greenlet import greenlet


__version__ = '0.0.1'


log = logging.getLogger(__name__)


class Timeout(Exception):
    pass


class Closed(Exception):
    pass


class Stop(Closed):
    pass


class Filter(Exception):
    pass


class Reraise(Exception):
    pass


class preserve_exception(object):
    """
    Marker to pass exceptions through channels
    """
    def __init__(self):
        self.typ, self.val, self.tb = sys.exc_info()

    def reraise(self):
        try:
            raise Reraise('Unhandled exception')
        except:
            traceback.print_exc()
            sys.stderr.write('\nOriginal exception -->\n\n')
            raise self.typ, self.val, self.tb


def ospipe():
    """creates an os pipe and sets it up for async io"""
    pipe_r, pipe_w = os.pipe()
    flags = fcntl.fcntl(pipe_w, fcntl.F_GETFL, 0)
    flags = flags | os.O_NONBLOCK
    fcntl.fcntl(pipe_w, fcntl.F_SETFL, flags)
    return pipe_r, pipe_w


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
    #define EPOLLERR ...
    #define EPOLLHUP ...
    #define EPOLLRDHUP ...

    #define SIGALRM ...
    #define SIGINT ...
    #define SIGTERM ...

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
    """)

    C = ffi.verify("""
        #include <unistd.h>
        #include <sys/eventfd.h>
        #include <sys/signalfd.h>
        #include <sys/epoll.h>
        #include <signal.h>
        #include <sys/inotify.h>
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

    return C


C = init_C()


class Event(object):
    """
    An event object manages an internal flag that can be set to true with the
    set() method and reset to false with the clear() method. The wait() method
    blocks until the flag is true.
    """

    __slots__ = ['hub', 'fired', 'waiters']

    def __init__(self, hub, fired=False):
        self.hub = hub
        self.fired = fired
        self.waiters = collections.deque()

    def __nonzero__(self):
        return self.fired

    def wait(self):
        if self.fired:
            return
        self.waiters.append(getcurrent())
        self.hub.pause()

    def set(self):
        self.fired = True
        # isolate this group of waiters in case of a clear
        waiters = self.waiters
        while waiters:
            waiter = waiters.popleft()
            self.hub.switch_to(waiter)

    def clear(self):
        self.fired = False
        # start a new list of waiters, which will block until the next set
        self.waiters = collections.deque()
        return self


class Channel(object):

    __slots__ = ['hub', 'closed', 'pipeline', 'items', 'waiters']

    def __init__(self, hub):
        self.hub = hub
        self.closed = False
        self.pipeline = None
        self.items = collections.deque()
        self.waiters = collections.deque()

    def __call__(self, f):
        if not self.pipeline:
            self.pipeline = []
        self.pipeline.append(f)

    def send(self, item):
        if self.closed:
            raise Closed

        if self.pipeline and not isinstance(item, Closed):
            try:
                for f in self.pipeline:
                    item = f(item)
            except Filter:
                return
            except Exception, e:
                item = e

        if not self.waiters:
            self.items.append(item)
            return

        getter = self.waiters.popleft()
        if isinstance(item, Exception):
            self.hub.throw_to(getter, item)
        else:
            self.hub.switch_to(getter, (self, item))

    def recv(self, timeout=-1):
        if self.items:
            item = self.items.popleft()
            if isinstance(item, preserve_exception):
                item.reraise()
            if isinstance(item, Exception):
                raise item
            return item

        if timeout == 0:
            raise Timeout('timeout: %s' % timeout)

        self.waiters.append(getcurrent())
        try:
            item = self.hub.pause(timeout=timeout)
            ch, item = item
        except Timeout:
            self.waiters.remove(getcurrent())
            raise
        return item

    def throw(self):
        self.send(preserve_exception())

    def __iter__(self):
        while True:
            try:
                yield self.recv()
            except Closed:
                raise StopIteration

    def close(self):
        self.send(Closed('closed'))
        self.closed = True


class Signal(object):
    def __init__(self, hub):
        self.hub = hub
        self.fd = -1
        self.count = 0
        self.mapper = {}
        self.reverse_mapper = {}

    def start(self, fd):
        self.fd = fd

        info = C.ffi.new('struct signalfd_siginfo *')
        size = C.ffi.sizeof('struct signalfd_siginfo')

        ready = self.hub.register(fd, select.EPOLLIN)

        @self.hub.spawn
        def _():
            while True:
                try:
                    fd, event = ready.recv()
                except Closed:
                    self.stop()
                    return

                rc = C.read(fd, info, size)
                assert rc == size

                num = info.ssi_signo
                for ch in self.mapper[num]:
                    ch.send(num)

    def stop(self):
        if self.fd == -1:
            return

        fd = self.fd
        self.fd = -1
        self.count = 0
        self.mapper = {}
        self.reverse_mapper = {}

        self.hub.unregister(fd)
        os.close(fd)

    def reset(self):
        if self.count == len(self.mapper):
            return

        self.count = len(self.mapper)

        if not self.count:
            self.stop()
            return

        mask = C.sigset(*self.mapper.keys())
        rc = C.sigprocmask(C.SIG_SETMASK, mask, C.NULL)
        assert not rc
        fd = C.signalfd(self.fd, mask, C.SFD_NONBLOCK | C.SFD_CLOEXEC)

        if self.fd == -1:
            self.start(fd)

    def subscribe(self, *signals):
        out = self.hub.channel()
        self.reverse_mapper[out] = signals
        for num in signals:
            self.mapper.setdefault(num, []).append(out)
        self.reset()
        return out

    def unsubscribe(self, ch):
        for num in self.reverse_mapper[ch]:
            self.mapper[num].remove(ch)
            if not self.mapper[num]:
                del self.mapper[num]
        del self.reverse_mapper[ch]
        self.reset()


class FD(object):
    def __init__(self, hub, fileno):
        self.hub = hub
        self.fileno = fileno

        self.events = hub.register(fileno, C.EPOLLIN | C.EPOLLHUP | C.EPOLLERR)

        self.hub.spawn(self.loop)
        self.pending = self.hub.channel()

    def loop(self):
        while True:
            try:
                fileno, event = self.events.recv()
                if event & select.EPOLLERR or event & select.EPOLLHUP:
                    raise Stop

                # read until exhaustion
                while True:
                    try:
                        data = os.read(self.fileno, 16384)
                    except OSError, e:
                        # resource unavailable, block until it is
                        if e.errno == 11:  # EAGAIN
                            break
                        raise Stop

                    if not data:
                        raise Stop

                    self.pending.send(data)

            except Stop:
                self.close()
                return

    def close(self):
        self.hub.unregister(self.fileno)
        """
        try:
            # TODO: this needs to be customizable
            self.conn.shutdown(socket.SHUT_RDWR)
        except:
            pass
        """
        os.close(self.fileno)

    def recv_bytes(self, n):
        if n == 0:
            return ''

        received = 0
        segments = []
        while received < n:
            segment = self.pending.recv()
            segments.append(segment)
            received += len(segment)

        # if we've received too much, break the last segment and return the
        # additional portion to pending
        overage = received - n
        if overage:
            self.pending.items.appendleft(segments[-1][-1*(overage):])
            segments[-1] = segments[-1][:-1*(overage)]

        return ''.join(segments)

    def recv_partition(self, sep):
        received = ''
        while True:
            received += self.pending.recv()
            keep, matched, additonal = received.partition(sep)
            if matched:
                if additonal:
                    self.pending.items.appendleft(additonal)
                return keep


class INotify(object):
    FLAG_TO_HUMAN = [
        (C.IN_ACCESS, 'access'),
        (C.IN_MODIFY, 'modify'),
        (C.IN_ATTRIB, 'attrib'),
        (C.IN_CLOSE_WRITE, 'close_write'),
        (C.IN_CLOSE_NOWRITE, 'close_nowrite'),
        (C.IN_OPEN, 'open'),
        (C.IN_MOVED_FROM, 'moved_from'),
        (C.IN_MOVED_TO, 'moved_to'),
        (C.IN_CREATE, 'create'),
        (C.IN_DELETE, 'delete'),
        (C.IN_DELETE_SELF, 'delete_self'),
        (C.IN_MOVE_SELF, 'move_self'),
        (C.IN_UNMOUNT, 'unmount'),
        (C.IN_Q_OVERFLOW, 'queue_overflow'),
        (C.IN_IGNORED, 'ignored'),
        (C.IN_ONLYDIR, 'only_dir'),
        (C.IN_DONT_FOLLOW, 'dont_follow'),
        (C.IN_MASK_ADD, 'mask_add'),
        (C.IN_ISDIR, 'is_dir'),
        (C.IN_ONESHOT, 'one_shot'), ]

    @staticmethod
    def humanize_mask(mask):
        s = []
        for k, v in INotify.FLAG_TO_HUMAN:
            if k & mask:
                s.append(v)
        return s

    def __init__(self, hub):
        self.hub = hub

        # TODO: refactor Stream, FD and all the other misc fd access in a sec
        self.fileno = C.inotify_init1(C.IN_NONBLOCK | C.IN_CLOEXEC)
        self.fd = FD(self.hub, self.fileno)

        self.wds = {}

        @hub.spawn
        def _():
            while True:
                notification = self.fd.recv_bytes(16)
                wd, mask, cookie, size = struct.unpack("=LLLL", notification)
                if size:
                    name = self.fd.recv_bytes(size).rstrip('\0')
                else:
                    name = None
                self.wds[wd].send((mask, name))

    def watch(self, path, mask=C.IN_ALL_EVENTS):
        wd = C.inotify_add_watch(self.fileno, path, mask)
        ch = self.hub.channel()
        self.wds[wd] = ch
        return ch


class Hub(object):
    def __init__(self):
        self.ready = collections.deque()
        self.scheduled = Scheduler()
        self.stopped = self.event()

        self.epoll = select.epoll()
        self.registered = {}

        self.signal = Signal(self)
        self.tcp = TCP(self)
        self.http = HTTP(self)

        self.loop = greenlet(self.main)

    def event(self, fired=False):
        return Event(self, fired)

    def channel(self):
        return Channel(self)

    # allows you to wait on a list of channels
    def select(self, *channels):
        for ch in channels:
            try:
                item = ch.recv(timeout=0)
                return ch, item
            except Timeout:
                continue

        for ch in channels:
            ch.waiters.append(getcurrent())

        try:
            fired, item = self.pause()
        except:
            for ch in channels:
                if getcurrent() in ch.waiters:
                    ch.waiters.remove(getcurrent())
            raise

        for ch in channels:
            if ch != fired:
                ch.waiters.remove(getcurrent())
        return fired, item

    def inotify(self):
        return INotify(self)

    def pause(self, timeout=-1):
        if timeout > -1:
            item = self.scheduled.add(
                timeout, getcurrent(), Timeout('timeout: %s' % timeout))

        resume = self.loop.switch()

        if timeout > -1:
            if isinstance(resume, Timeout):
                raise resume

            # since we didn't timeout, remove ourselves from scheduled
            self.scheduled.remove(item)

        # TODO: clean up stopped handling here
        if self.stopped:
            raise Closed('closed')

        return resume

    def switch_to(self, target, *a):
        self.ready.append((getcurrent(), ()))
        return target.switch(*a)

    def throw_to(self, target, *a):
        self.ready.append((getcurrent(), ()))
        if len(a) == 1 and isinstance(a[0], preserve_exception):
            return target.throw(a[0].typ, a[0].val, a[0].tb)
        return target.throw(*a)

    def spawn(self, f, *a):
        self.ready.append((f, a))

    def spawn_later(self, ms, f, *a):
        self.scheduled.add(ms, f, *a)

    def sleep(self, ms=1):
        self.scheduled.add(ms, getcurrent())
        self.loop.switch()

    def register(self, fd, mask):
        self.registered[fd] = self.channel()
        self.epoll.register(fd, mask)
        return self.registered[fd]

    def unregister(self, fd):
        if fd in self.registered:
            try:
                # TODO: investigate why this could error
                self.epoll.unregister(fd)
            except:
                pass
            self.registered[fd].close()
            del self.registered[fd]

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

    def stop_on_term(self):
        done = self.signal.subscribe(C.SIGINT, C.SIGTERM)
        done.recv()
        self.stop()

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
        def run_task(task, *a):
            if isinstance(task, greenlet):
                task.switch(*a)
            else:
                greenlet(task).switch(*a)

        while True:
            while self.ready:
                task, a = self.ready.popleft()
                run_task(task, *a)

            if self.scheduled:
                timeout = self.scheduled.timeout()
                # run overdue scheduled immediately
                if timeout < 0:
                    task, a = self.scheduled.pop()
                    run_task(task, *a)
                    continue

                # if nothing registered, just sleep until next scheduled
                if not self.registered:
                    time.sleep(timeout)
                    task, a = self.scheduled.pop()
                    run_task(task, *a)
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
                run_task(task, *a)

            else:
                for fd, event in events:
                    if fd in self.registered:
                        self.registered[fd].send((fd, event))


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


# TCP ######################################################################


class TCP(object):
    def __init__(self, hub):
        self.hub = hub

    def listen(self, port=0, host='127.0.0.1'):
        return TCPListener(self.hub, host, port)

    def connect(self, port, host='127.0.0.1'):
        return TCPConn.connect(self.hub, host, port)


"""
struct.pack reference
uint32: "I"
uint64: 'Q"

Packet
    type|size: uint32 (I)
        type (2 bits):
            PUSH    = 0
            REQUEST = 1
            REPLY   = 2
            OP      = 3
        size (30 bits, 1GB)    # for type PUSH/REQUEST/REPLY
        or OPCODE for type OP
            1  = OP_PING
            2  = OP_PONG

    route: uint32 (I)          # optional for REQUEST and REPLY
    buffer: bytes len(size)

TCPConn supports Bi-Directional Push->Pull and Request<->Response
"""

PACKET_PUSH = 0
PACKET_REQUEST = 1 << 30
PACKET_REPLY = 2 << 30
PACKET_TYPE_MASK = PACKET_REQUEST | PACKET_REPLY
PACKET_SIZE_MASK = ~PACKET_TYPE_MASK


class TCPConn(object):
    @classmethod
    def connect(klass, hub, host, port):
        conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        conn.connect((host, port))
        conn.setblocking(0)
        return klass(hub, conn)

    def __init__(self, hub, conn):
        self.hub = hub
        self.conn = conn
        self.conn.setblocking(0)
        self.stopping = False
        self.closed = False

        # used to track calls, and incoming requests
        self.call_route = 0
        self.call_outstanding = {}

        self.pull = hub.channel()

        self.serve = hub.channel()
        self.serve_in_progress = 0
        ##

        self.recv_ready = hub.event(True)
        self.recv_buffer = ''
        self.recv_closed = False

        self.pong = hub.event(False)

        self.events = hub.register(
            conn.fileno(),
            select.EPOLLIN | select.EPOLLHUP | select.EPOLLERR)

        hub.spawn(self.event_loop)
        hub.spawn(self.recv_loop)

    def event_loop(self):
        while True:
            try:
                fd, event = self.events.recv()
                if event & select.EPOLLERR or event & select.EPOLLHUP:
                    self.close()
                    return
                if event & select.EPOLLIN:
                    if self.recv_closed:
                        if not self.serve_in_progress:
                            self.close()
                        return
                    self.recv_ready.set()
            except Closed:
                self.stop()

    def recv_loop(self):
        def recvn(n):
            if n == 0:
                return ''

            ret = ''
            while True:
                m = n - len(ret)
                if self.recv_buffer:
                    ret += self.recv_buffer[:m]
                    self.recv_buffer = self.recv_buffer[m:]

                if len(ret) >= n:
                    break

                try:
                    self.recv_buffer = self.conn.recv(max(m, 4096))
                except socket.error, e:
                    # resource unavailable, block until it is
                    if e.errno == 11:  # EAGAIN
                        self.recv_ready.clear().wait()
                        continue
                    raise

                if not self.recv_buffer:
                    raise socket.error('closing connection')

            return ret

        while True:
            try:
                typ_size, = struct.unpack('<I', recvn(4))

                # handle ping / pong
                if PACKET_TYPE_MASK & typ_size == PACKET_TYPE_MASK:
                    if typ_size & PACKET_SIZE_MASK == 1:
                        # ping received, send pong
                        self._send(struct.pack('<I', PACKET_TYPE_MASK | 2))
                    else:
                        # pong recieved
                        self.pong.set()
                        self.pong.clear()
                    continue

                if PACKET_TYPE_MASK & typ_size:
                    route, = struct.unpack('<I', recvn(4))

                data = recvn(typ_size & PACKET_SIZE_MASK)

                if typ_size & PACKET_REQUEST:
                    self.serve_in_progress += 1
                    self.serve.send((route, data))
                    continue

                if typ_size & PACKET_REPLY:
                    if route not in self.call_outstanding:
                        log.warning('Missing route: %s' % route)
                        continue
                    self.call_outstanding[route].send(data)
                    del self.call_outstanding[route]
                    if not self.call_outstanding and self.stopping:
                        self.close()
                        break
                    continue

                # push packet
                self.pull.send(data)
                continue

            except Exception, e:
                if type(e) != socket.error:
                    log.exception(e)
                self.recv_closed = True
                self.stop()
                break

    def push(self, data):
        self.send(0, PACKET_PUSH, data)

    def call(self, data):
        # TODO: handle wrap around
        self.call_route += 1
        self.call_outstanding[self.call_route] = self.hub.channel()
        self.send(self.call_route, PACKET_REQUEST, data)
        return self.call_outstanding[self.call_route]

    def reply(self, route, data):
        self.send(route, PACKET_REPLY, data)
        self.serve_in_progress -= 1
        if not self.serve_in_progress and self.stopping:
            self.close()

    def ping(self):
        self._send(struct.pack('<I', PACKET_TYPE_MASK | 1))

    def send(self, route, typ, data):
        assert len(data) < 2**30, 'Data must be less than 1Gb'

        # TODO: is there away to avoid the duplication of data here?
        if PACKET_TYPE_MASK & typ:
            message = struct.pack('<II', typ | len(data), route) + data
        else:
            message = struct.pack('<I', typ | len(data)) + data

        self._send(message)

    def _send(self, message):
        try:
            self.conn.send(message)
        except Exception, e:
            if type(e) != socket.error:
                log.exception(e)
            self.close()
            raise

    def stop(self):
        if self.call_outstanding or self.serve_in_progress:
            self.stopping = True
            # if we aren't waiting for a reply, shutdown our read pipe
            if not self.call_outstanding:
                self.hub.unregister(self.conn.fileno())
                self.conn.shutdown(socket.SHUT_RD)
            return

        # nothing in progress, just close
        self.close()

    def close(self):
        if not self.closed:
            self.closed = True
            self.hub.unregister(self.conn.fileno())
            try:
                self.conn.shutdown(socket.SHUT_RDWR)
            except:
                pass
            self.conn.close()
            for ch in self.call_outstanding.values():
                ch.send(Exception('connection closed.'))
            self.serve.close()


class TCPListener(object):
    def __init__(self, hub, host, port):
        self.hub = hub
        self.sock = s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((host, port))
        s.listen(socket.SOMAXCONN)
        s.setblocking(0)

        self.port = s.getsockname()[1]
        self.accept = hub.channel()

        self.ch = hub.register(s.fileno(), select.EPOLLIN)
        hub.spawn(self.loop)

    def loop(self):
        while True:
            try:
                self.ch.recv()
                conn, host = self.sock.accept()
                conn = TCPConn(self.hub, conn)
                self.accept.send(conn)
            except Stop:
                self.stop()
                return

    def stop(self):
        self.hub.unregister(self.sock.fileno())
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except:
            pass
        self.sock.close()


# HTTP #####################################################################


HTTP_VERSION = 'HTTP/1.1'


class Insensitive(object):
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


class HTTP(object):
    def __init__(self, hub):
        self.hub = hub

    def listen(self, port=0, host='127.0.0.1', server=None):
        if server:
            return HTTPListener(self.hub, host, port, server)
        return functools.partial(HTTPListener, self.hub, host, port)

    def connect(self, url):
        return HTTPClient(self.hub, url)


class Stream(object):
    def __init__(self, hub, conn):
        self.hub = hub
        self.conn = conn
        self.fileno = conn.fileno()

        self.events = hub.register(
            conn.fileno(),
            C.EPOLLIN | C.EPOLLHUP | C.EPOLLERR)

        self.hub.spawn(self.loop)
        self.pending = self.hub.channel()

    def loop(self):
        while True:
            try:
                fd, event = self.events.recv()
                if event & select.EPOLLERR or event & select.EPOLLHUP:
                    raise Stop

                # read conn until exhaustion
                while True:
                    try:
                        data = self.conn.recv(16384)
                    except socket.error, e:
                        # resource unavailable, block until it is
                        if e.errno == 11:  # EAGAIN
                            break
                        raise Stop

                    if not data:
                        raise Stop

                    self.pending.send(data)

            except Stop:
                self.close()
                return

    def close(self):
        self.hub.unregister(self.fileno)
        try:
            self.conn.shutdown(socket.SHUT_RDWR)
        except:
            pass
        self.conn.close()

    def recv_bytes(self, n):
        if n == 0:
            return ''

        received = 0
        segments = []
        while received < n:
            segment = self.pending.recv()
            segments.append(segment)
            received += len(segment)

        # if we've received too much, break the last segment and return the
        # additional portion to pending
        overage = received - n
        if overage:
            self.pending.items.appendleft(segments[-1][-1*(overage):])
            segments[-1] = segments[-1][:-1*(overage)]

        return ''.join(segments)

    def recv_partition(self, sep):
        received = ''
        while True:
            received += self.pending.recv()
            keep, matched, additonal = received.partition(sep)
            if matched:
                if additonal:
                    self.pending.items.appendleft(additonal)
                return keep


class HTTPCore(object):
    def __init__(self, stream):
        self.stream = stream

    def recv_bytes(self, n):
        return self.stream.recv_bytes(n)

    def recv_line(self):
        return self.stream.recv_partition('\r\n')

    def recv_headers(self):
        headers = Insensitive()
        while True:
            line = self.recv_line()
            if not line:
                break
            k, v = line.split(': ', 1)
            headers[k] = v
        return headers


class WebSocket(object):
    MASK = FIN = 0b10000000
    RSV = 0b01110000
    OP = 0b00001111
    PAYLOAD = 0b01111111

    OP_TEXT = 0x1
    OP_BIN = 0x2
    OP_CLOSE = 0x8
    OP_PING = 0x9
    OP_PONG = 0xA

    SANITY = 1024**3  # limit fragments to 1GB

    def __init__(self, stream, is_client=True):
        self.stream = stream
        self.is_client = is_client

    @staticmethod
    def mask(mask, s):
        mask_bytes = [ord(c) for c in mask]
        return ''.join(
            chr(mask_bytes[i % 4] ^ ord(c)) for i, c in enumerate(s))

    @staticmethod
    def accept_key(key):
        value = key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
        return base64.b64encode(hashlib.sha1(value).digest())

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
            self.stream.conn.sendall(header + mask + self.mask(mask, data))
        else:
            self.stream.conn.sendall(header + data)

    def recv(self):
        b1, length, = struct.unpack('!BB', self.stream.recv_bytes(2))
        assert b1 & WebSocket.FIN, "Fragmented messages not supported yet"

        if self.is_client:
            assert not length & WebSocket.MASK
        else:
            assert length & WebSocket.MASK
            length = length & WebSocket.PAYLOAD

        if length == 126:
            length, = struct.unpack('!H', self.stream.recv_bytes(2))

        elif length == 127:
            length, = struct.unpack('!Q', self.stream.recv_bytes(8))

        assert length < WebSocket.SANITY, "Frames limited to 1Gb for sanity"

        if self.is_client:
            return self.stream.recv_bytes(length)

        mask = self.stream.recv_bytes(4)
        return self.mask(mask, self.stream.recv_bytes(length))


class HTTPClient(object):
    Status = collections.namedtuple('Status', ['version', 'code', 'message'])

    def __init__(self, hub, url):
        self.hub = hub

        parsed = urlparse.urlsplit(url)
        assert parsed.query == ''
        assert parsed.fragment == ''
        host, port = urllib.splitnport(parsed.netloc, 80)

        self.conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.conn.connect((host, port))
        self.conn.setblocking(0)

        self.http = HTTPCore(Stream(hub, self.conn))

        self.agent = 'vanilla/%s' % __version__

        self.default_headers = dict([
            ('Accept', '*/*'),
            ('User-Agent', self.agent),
            ('Host', parsed.netloc), ])
            # ('Connection', 'Close'), ])

        self.responses = collections.deque()
        hub.spawn(self.receiver)

    def receiver(self):
        while True:
            version, code, message = self.http.recv_line().split(' ', 2)
            code = int(code)
            status = self.Status(version, code, message)

            ch = self.responses.popleft()
            ch.send(status)

            headers = self.http.recv_headers()
            ch.send(headers)

            # If our connection is upgraded, shutdown the HTTP receive loop, as
            # this is no longer a HTTP connection.
            if headers.get('connection') == 'Upgrade':
                ch.close()
                return

            if headers.get('transfer-encoding') == 'chunked':
                while True:
                    length = int(self.http.recv_line())
                    if length:
                        chunk = self.http.recv_bytes(length)
                        ch.send(chunk)
                    assert self.http.recv_bytes(2) == '\r\n'
                    if not length:
                        break
            else:
                # TODO:
                # http://www.w3.org/Protocols/rfc2616/rfc2616-sec4.html#sec4.4
                body = self.http.recv_bytes(int(headers['content-length']))
                ch.send(body)

            ch.close()

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
        headers = '\r\n'.join(
            '%s: %s' % (k, v) for k, v in request_headers.iteritems())

        self.conn.sendall(request+headers+'\r\n'+'\r\n')

        ch = self.hub.channel()
        self.responses.append(ch)
        return ch

    def get(self, path='/', params=None, headers=None, version=HTTP_VERSION):
        return self.request('GET', path, params, headers, version)

    def websocket(
            self, path='/', params=None, headers=None, version=HTTP_VERSION):

        key = base64.b64encode(uuid.uuid4().bytes)

        headers = headers or {}
        headers.update({
            'Upgrade': 'WebSocket',
            'Connection': 'Upgrade',
            'Sec-WebSocket-Key': key,
            'Sec-WebSocket-Version': 13, })

        response = self.request('GET', path, params, headers, version)

        status = response.recv()
        assert status.code == 101

        headers = response.recv()
        assert headers['Upgrade'].lower() == 'websocket'
        assert headers['Sec-WebSocket-Accept'] == WebSocket.accept_key(key)

        return WebSocket(self.http.stream)


class HTTPListener(object):
    def __init__(self, hub, host, port, server):
        self.hub = hub

        self.sock = s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((host, port))
        s.listen(socket.SOMAXCONN)
        s.setblocking(0)

        self.port = s.getsockname()[1]
        self.server = server

        hub.spawn(self.accept)

    def accept(self):
        ready = self.hub.register(self.sock.fileno(), select.EPOLLIN)
        while True:
            try:
                ready.recv()
                conn, host = self.sock.accept()
                self.hub.spawn(self.serve, conn)
            except Stop:
                self.stop()
                return

    def serve(self, conn):
        conn.setblocking(0)
        http = HTTPCore(Stream(self.hub, conn))

        #TODO: support http keep alives

        Request = collections.namedtuple(
            'Request', ['method', 'path', 'version', 'headers'])

        class Response(object):
            def __init__(self, request, out):
                self.request = request
                self.out = out

                self.status = (200, 'OK')
                self.headers = {}
                self.headers_sent = False
                self.is_upgraded = False

            def send(self, data):
                self.out.send(data)

            def end(self, data):
                if not self.is_upgraded:
                    self.data = data or ''
                    self.out.close()

            def upgrade(self):
                assert self.request.headers['Connection'].lower() == 'upgrade'
                assert self.request.headers['Upgrade'].lower() == 'websocket'

                key = self.request.headers['Sec-WebSocket-Key']
                accept = WebSocket.accept_key(key)

                self.status = (101, 'Switching Protocols')
                self.headers.update({
                    "Upgrade": "websocket",
                    "Connection": "Upgrade",
                    "Sec-WebSocket-Accept": accept, })
                self._send_headers()

                self.is_upgraded = True
                self.out.close()

                return WebSocket(http.stream, is_client=False)

            def _send_headers(self):
                assert not self.headers_sent
                status = 'HTTP/1.1 %s %s\r\n' % (self.status)
                headers = '\r\n'.join(
                    '%s: %s' % (k, v) for k, v in self.headers.iteritems())
                conn.sendall(status+headers+'\r\n'+'\r\n')
                self.headers_sent = True

            def _send_chunk(self, chunk):
                if not self.headers_sent:
                    self.headers['Transfer-Encoding'] = 'chunked'
                    self._send_headers()
                conn.sendall('%s\r\n%s\r\n' % (hex(len(chunk))[2:], chunk))

            def _send_body(self, body):
                self.headers['Content-Length'] = len(body)
                self._send_headers()
                conn.sendall(body)

        method, path, version = http.recv_line().split(' ', 2)
        headers = http.recv_headers()
        request = Request(method, path, version, headers)

        response = Response(request, self.hub.channel())

        @self.hub.spawn
        def _():
            data = self.server(request, response)
            response.end(data)

        for chunk in response.out:
            response._send_chunk(chunk)

        if response.is_upgraded:
            # connection was upgraded, bail, as this is no longer a HTTP
            # connection
            return

        if response.headers_sent:
            # this must be a chunked transfer
            if response.data:
                response._send_chunk(response.data)
            response._send_chunk('')

        else:
            response._send_body(response.data)

        conn.close()

    def stop(self):
        self.hub.unregister(self.sock.fileno())
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except:
            pass
        self.sock.close()
