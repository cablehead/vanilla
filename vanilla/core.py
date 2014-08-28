# Organ pipe arrangement of imports; because Guido likes it

import collections
import functools
import importlib
import mimetypes
import urlparse
import weakref
import hashlib
import logging
import urllib
import struct
import select
import socket
import base64
import fcntl
import heapq
import cffi
import uuid
import time
import ssl
import os
import io


from greenlet import getcurrent
from greenlet import greenlet


__version__ = '0.0.1'


log = logging.getLogger(__name__)


class Timeout(Exception):
    pass


class Halt(Exception):
    pass


class Stop(Halt):
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


Paired = collections.namedtuple('Paired', ['sender', 'recver'])


class Paired(Paired):
    def send(self, *a, **kw):
        return self.sender.send(*a, **kw)

    def recv(self, *a, **kw):
        return self.recver.recv(*a, **kw)

    def pipe(self, *a, **kw):
        return self.recver.pipe(*a, **kw)

    def connect(self, *a, **kw):
        return self.sender.connect(*a, **kw)

    def map(self, *a, **kw):
        return self.recver.map(*a, **kw)

    def consume(self, *a, **kw):
        return self.recver.consume(*a, **kw)


class Pipe(object):
    __slots__ = [
        'hub', 'recver', 'recver_current', 'sender', 'sender_current',
        'closed']

    def __new__(cls, hub):
        self = super(Pipe, cls).__new__(cls)
        self.hub = hub
        self.closed = False

        recver = Recver(self)
        self.recver = weakref.ref(recver, self.on_abandoned)
        self.recver_current = None

        sender = Sender(self)
        self.sender = weakref.ref(sender, self.on_abandoned)
        self.sender_current = None

        return Paired(sender, recver)

    def on_abandoned(self, *a, **kw):
        remaining = self.recver() or self.sender()
        if remaining:
            remaining.abandoned()


class End(object):
    __slots__ = ['middle']

    def __init__(self, pipe):
        self.middle = pipe

    @property
    def hub(self):
        return self.middle.hub

    @property
    def halted(self):
        return bool(self.middle.closed or self.other is None)

    @property
    def ready(self):
        if self.middle.closed:
            raise Closed
        if self.other is None:
            raise Abandoned
        return bool(self.other.current)

    def select(self):
        assert self.current is None
        self.current = getcurrent()

    def unselect(self):
        assert self.current == getcurrent()
        self.current = None

    def abandoned(self):
        if self.current:
            self.hub.throw_to(self.current, Abandoned)

    @property
    def peak(self):
        return self.current

    def pause(self, timeout=-1):
        self.select()
        try:
            _, ret = self.hub.pause(timeout=timeout)
        finally:
            self.unselect()
        return ret

    def close(self):
        if self.other is not None and bool(self.other.current):
            self.hub.throw_to(self.other.current, Closed)
        self.middle.closed = True


class Sender(End):
    @property
    def current(self):
        return self.middle.sender_current

    @current.setter
    def current(self, value):
        self.middle.sender_current = value

    @property
    def other(self):
        return self.middle.recver()

    def send(self, item, timeout=-1):
        if not self.ready:
            self.pause(timeout=timeout)

        if isinstance(item, Exception):
            return self.hub.throw_to(self.other.peak, item)

        return self.hub.switch_to(self.other.peak, self.other, item)

    def connect(self, recver):
        """
        Rewire:
            s1 -> m1 <- r1 --> s2 -> m2 <- r2
        To:
            s1 -> m1 <- r2
        """
        r1 = recver
        m1 = r1.middle
        s2 = self
        m2 = self.middle
        r2 = self.other

        r2.middle = m1
        m1.recver = weakref.ref(r2, m1.on_abandoned)
        m1.recver_current = m2.recver_current
        del r1.middle
        del s2.middle
        return r2


class Recver(End):
    @property
    def current(self):
        return self.middle.recver_current

    @current.setter
    def current(self, value):
        self.middle.recver_current = value

    @property
    def other(self):
        return self.middle.sender()

    def recv(self, timeout=-1):
        if self.ready:
            self.select()
            # switch directly, as we need to pause
            _, ret = self.other.peak.switch(self.other, None)
            self.unselect()
            return ret

        return self.pause(timeout=timeout)

    def __iter__(self):
        while True:
            try:
                yield self.recv()
            except Halt:
                break

    def pipe(self, sender):
        if callable(sender):
            pipe = self.hub.pipe()
            self.hub.spawn(sender, self, pipe.sender)
            return pipe.recver
        else:
            return sender.connect(self)

    def map(self, f):
        @self.pipe
        def recver(recver, sender):
            for item in recver:
                sender.send(f(item))
        return recver

    def consume(self, f):
        @self.hub.spawn
        def _():
            for item in self:
                f(item)


def Queue(hub, size):
    assert size > 0

    def main(upstream, downstream, size):
        queue = collections.deque()

        while True:
            if downstream.halted:
                # no one is downstream, so shutdown
                upstream.close()
                return

            watch = []
            if queue:
                watch.append(downstream)
            else:
                # if the buffer is empty, and no one is upstream, shutdown
                if upstream.halted:
                    downstream.close()
                    return

            # if are upstream is still available, and there is spare room in
            # the buffer, watch upstream as well
            if not upstream.halted and len(queue) < size:
                watch.append(upstream)

            try:
                ch, item = hub.select(watch)
            except Halt:
                continue

            if ch == upstream:
                queue.append(item)

            elif ch == downstream:
                item = queue.popleft()
                downstream.send(item)

    upstream = hub.pipe()
    downstream = hub.pipe()

    # TODO: rethink this
    old_connect = upstream.sender.connect

    def connect(recver):
        old_connect(recver)
        return downstream.recver

    upstream.sender.connect = connect

    hub.spawn(main, upstream.recver, downstream.sender, size)
    return Paired(upstream.sender, downstream.recver)


class Dealer(object):
    class Recver(Recver):
        def select(self):
            assert getcurrent() not in self.current
            self.current.append(getcurrent())

        def unselect(self):
            self.current.remove(getcurrent())

        @property
        def peak(self):
            return self.current[0]

        def abandoned(self):
            waiters = list(self.current)
            for current in waiters:
                self.hub.throw_to(current, Abandoned)

    def __new__(cls, hub):
        sender, recver = hub.pipe()
        recver.__class__ = Dealer.Recver
        recver.current = collections.deque()
        return Paired(sender, recver)


class Router(object):
    class Sender(Sender):
        def select(self):
            assert getcurrent() not in self.current
            self.current.append(getcurrent())

        def unselect(self):
            self.current.remove(getcurrent())

        @property
        def peak(self):
            return self.current[0]

        def abandoned(self):
            waiters = list(self.current)
            for current in waiters:
                self.hub.throw_to(current, Abandoned)

        def connect(self, recver):
            recver.consume(self.send)

    def __new__(cls, hub):
        sender, recver = hub.pipe()
        sender.__class__ = Router.Sender
        sender.current = collections.deque()
        return Paired(sender, recver)


class Broadcast(object):
    def __init__(self, hub):
        self.hub = hub
        self.subscribers = []

    def send(self, item):
        to_remove = None
        for subscriber in self.subscribers:
            try:
                if subscriber.ready:
                    subscriber.send(item)
            except Halt:
                to_remove = to_remove or []
                to_remove.append(subscriber)
        if to_remove:
            self.subscribers = [
                x for x in self.subscribers if x not in to_remove]

    def subscribe(self):
        sender, recver = self.hub.pipe()
        self.subscribers.append(sender)
        return recver

    def connect(self, recver):
        recver.consume(self.send)


class Value(object):
    def __init__(self, hub):
        self.hub = hub
        self.waiters = []

    def send(self, item):
        self.value = item
        for waiter in self.waiters:
            self.hub.switch_to(waiter)

    def recv(self, timeout=-1):
        if not hasattr(self, 'value'):
            self.waiters.append(getcurrent())
            self.hub.pause(timeout=timeout)
        return self.value

    @property
    def ready(self):
        return hasattr(self, 'value')

    def clear(self):
        delattr(self, 'value')


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

        self.stopped = self.value()

        self.epoll = select.epoll()
        self.registered = {}

        self.poll = Poll(self)
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
        return Pipe(self)

    def producer(self, f):
        sender, recver = self.pipe()
        self.spawn(f, sender)
        return recver

    def pulse(self, ms, item=True):
        @self.producer
        def _(sender):
            while True:
                try:
                    self.sleep(ms)
                except Halt:
                    break
                sender.send(item)
            sender.close()
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
        def consume(recver, f):
            for item in recver:
                f()
        sender, recver = self.pipe()
        self.spawn(consume, recver, f)
        sender.trigger = functools.partial(sender.send, True)
        return sender

    def queue(self, size):
        return Queue(self, size)

    def channel(self, size=-1):
        sender, recver = self.router()
        if size > 0:
            recver = recver.pipe(self.queue(size))
        return Paired(sender, recver.pipe(self.dealer()))

    def broadcast(self):
        return Broadcast(self)

    def value(self):
        return Value(self)

    def dealer(self):
        return Dealer(self)

    def router(self):
        return Router(self)

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

        # TODO: rework Value's is set test to be more natural
        if self.stopped.ready:
            raise Stop(
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

    def stop(self):
        self.sleep(1)

        for fd, ch in self.registered.items():
            ch.send(Stop('stop'))

        while self.scheduled:
            task, a = self.scheduled.pop()
            self.throw_to(task, Stop('stop'))

        try:
            self.stopped.recv()
        except Halt:
            return

    def stop_on_term(self):
        self.signal.subscribe(C.SIGINT, C.SIGTERM).recv()
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
                self.stopped.send(True)
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
        self.fileno = self.conn.fileno()

        self.closed = False

        self.timeout = -1
        self.line_break = '\n'

        self.events = self.hub.register(
            self.fileno,
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
                data = self.conn.recv(4096)
            except (socket.error, OSError), e:
                if e.errno == 11:  # EAGAIN
                    break
                self.recv_sender.close()
                return
            if not data:
                self.recv_sender.close()
                return
            self.recv_sender.send(data)

    def writer(self):
        for data in self.send_recver:
            while True:
                try:
                    n = self.conn.send(data)
                except (socket.error, OSError), e:
                    if e.errno == 11:  # EAGAIN
                        raise
                    self.send_recver.close()
                    return
                if n == len(data):
                    break
                data = data[n:]

    def main(self):
        for fileno, event in self.events:
            if event & C.EPOLLIN:
                self.trigger_reader.trigger()

            elif event & C.EPOLLOUT:
                # self.trigger_writer()
                pass

            else:
                print "YARG", self.humanize_mask(event)

        self.close()

    def close(self):
        self.closed = True
        self.recv_sender.close()
        self.send_recver.close()
        self.hub.unregister(self.fileno)
        try:
            self.conn.close()
        except:
            pass


class Signal(object):
    def __init__(self, hub):
        self.hub = hub
        self.fileno = -1
        self.count = 0
        self.mapper = {}

    def subscribe(self, *signals):
        router = self.hub.router()
        for num in signals:
            if num not in self.mapper:
                self.mapper[num] = self.hub.broadcast()
            self.mapper[num].subscribe().pipe(router)
        self.reset()
        return router.recver

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
        fileno = C.signalfd(self.fileno, mask, C.SFD_NONBLOCK | C.SFD_CLOEXEC)

        if self.fileno == -1:
            self.start(fileno)

    def start(self, fileno):
        self.fileno = fileno
        self.fd = self.hub.poll.fileno(self.fileno)

        @self.hub.spawn
        def _():
            size = C.ffi.sizeof('struct signalfd_siginfo')
            info = C.ffi.new('struct signalfd_siginfo *')
            while True:
                try:
                    data = io.BytesIO(self.fd.recv_bytes(size))
                except Halt:
                    self.hub.unregister(self.fileno)
                    return
                data.readinto(C.ffi.buffer(info))
                num = info.ssi_signo
                self.mapper[num].send(num)

    def stop(self):
        raise Exception('TODO')


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
            try:
                ready.recv()
            except Halt:
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

    def bean(
            self,
            port=0,
            host='127.0.0.1',
            request_timeout=20000,
            base_path=None):
        return HTTPBean(self.hub, host, port, base_path, request_timeout)


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
            chunk = self.socket.recv_bytes(length)
        else:
            chunk = ''
        assert self.socket.recv_bytes(2) == '\r\n'
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

    def __init__(self, hub, url):
        self.hub = hub

        parsed = urlparse.urlsplit(url)
        assert parsed.query == ''
        assert parsed.fragment == ''

        default_port = 443 if parsed.scheme == 'https' else 80
        host, port = urllib.splitnport(parsed.netloc, default_port)

        self.socket = self.hub.tcp.connect(host=host, port=port)

        if parsed.scheme == 'https':
            self.socket.conn = ssl.wrap_socket(self.socket.conn)
            self.socket.conn.setblocking(0)

        self.socket.line_break = '\r\n'

        self.agent = 'vanilla/%s' % __version__

        self.default_headers = dict([
            ('Accept', '*/*'),
            ('User-Agent', self.agent),
            ('Host', parsed.netloc), ])

        # TODO: fix API
        self.responses, recver = self.hub.queue(1000)
        recver.pipe(self.hub.consumer(self.reader))

    def reader(self, response):
        version, code, message = self.socket.recv_line().split(' ', 2)
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

        if headers.get('transfer-encoding') == 'chunked':
            while True:
                chunk = self.recv_chunk()
                if not chunk:
                    break
                sender.send(chunk)
        else:
            # TODO:
            # http://www.w3.org/Protocols/rfc2616/rfc2616-sec4.html#sec4.4
            body = self.socket.recv_bytes(int(headers['content-length']))
            sender.send(body)

        sender.close()

    def request(
            self,
            method,
            path='/',
            params=None,
            headers=None,
            data=None):

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
            request_headers['Content-Length'] = len(data)
        self.send_headers(request_headers)

        # TODO: handle chunked transfers
        if data is not None:
            self.socket.send(data)

        sender, recver = self.hub.pipe()
        self.responses.send(sender)
        return recver

    def get(self, path='/', params=None, headers=None):
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
            assert self.request.headers['Connection'].lower() == 'upgrade'
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
                request = self.recv_request()

            except Halt:
                return

            except Timeout:
                print "Request Timeout"
                self.send_response(408, 'Request Timeout')
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
        code, message = response.recv()
        self.send_response(code, message)

        headers = response.recv()
        self.send_headers(headers)

        if headers.get('Connection') == 'Upgrade':
            return

        if headers.get('Transfer-Encoding') == 'chunked':
            for chunk in response:
                self.send_chunk(chunk)
            self.send_chunk('')
        else:
            self.socket.send(response.recv())

    def recv_request(self, timeout=None):
        method, path, version = self.socket.recv_line().split(' ', 2)
        headers = self.recv_headers()
        request = self.Request(method, path, version, headers)
        # TODO: handle chunked transfers
        length = int(headers.get('content-length', 0))
        request.body = self.socket.recv_bytes(length)
        return request

    def send_response(self, code, message):
        self.socket.send('HTTP/1.1 %s %s\r\n' % (code, message))


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
            except Halt:
                sender.close()
                return

    def recv(self):
        return self.recver.recv()

    def _recv(self):
        b1, length, = struct.unpack('!BB', self.socket.recv_bytes(2))
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
                self.socket.recv_bytes(length)
                self.socket.close()
                raise Closed

        if length == 126:
            length, = struct.unpack('!H', self.socket.recv_bytes(2))

        elif length == 127:
            length, = struct.unpack('!Q', self.socket.recv_bytes(8))

        assert length < WebSocket.SANITY, "Frames limited to 1Gb for sanity"

        if self.is_client:
            return self.socket.recv_bytes(length)

        mask = self.socket.recv_bytes(4)
        return self.mask(mask, self.socket.recv_bytes(length))

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
            self.socket.send(header + mask + self.mask(mask, data))
        else:
            self.socket.send(header + data)

    def close(self):
        if not self.socket.closed:
            MASK = WebSocket.MASK if self.is_client else 0
            header = struct.pack(
                '!BB',
                WebSocket.OP_CLOSE | WebSocket.FIN,
                MASK)
            self.socket.send(header)
            self.socket.close()


class HTTPBean(object):
    """
    Obligatory Sintra style micro-web framework

    TODO: all of HTTP should go into it's own module, but in-particular this
    *really* should!
    """
    def __init__(self, hub, host, port, base_path, request_timeout):
        # 3rd party dependency
        import routes

        self.hub = hub
        self.base_path = base_path

        self.server = self.hub.http.listen(
            host=host,
            port=port,
            request_timeout=request_timeout,
            serve=self.serve)

        self.port = self.server.port

        self.routes = routes.Mapper()
        self.actions = {}

    def path(self, *a):
        # TODO: this isn't secure, use something like twisted.python.filepath
        if self.base_path is not None:
            a = [self.base_path] + list(a)
        return os.path.join(*a)

    def serve(self, request, response):
        path, query = urllib.splitquery(request.path)

        if request.headers.get('upgrade', '').lower() == 'websocket':
            environ = {'REQUEST_METHOD': 'WEBSOCKET'}
        else:
            environ = {'REQUEST_METHOD': request.method}
        match = self.routes.match(path, environ=environ)

        if not match:
            response.status = (404, 'Not Found')
            return 'Sorry chief, page not found.'

        f = match.pop('f')
        return f(request, response, **match)

    def _add_route(self, path, conditions, f):
        def wrap(*a, **kw):
            target = self.actions[f]
            return target(*a, **kw)

        f.action = f
        self.actions[f] = f

        if conditions:
            self.routes.connect(path, f=wrap, conditions=conditions)
        else:
            self.routes.connect(path, f=wrap)
        return f

    def route(self, path):
        return functools.partial(self._add_route, path, None)

    def get(self, path):
        return functools.partial(self._add_route, path, {'method': ['GET']})

    def post(self, path):
        return functools.partial(self._add_route, path, {'method': ['POST']})

    def put(self, path):
        return functools.partial(self._add_route, path, {'method': ['PUT']})

    def websocket(self, path):
        def match(environ, match_dict):
            return environ.get('REQUEST_METHOD') == 'WEBSOCKET'

        def upgrade(request, response):
            upgrade.handler(response.upgrade())

        self._add_route(path, {'function': match}, upgrade)
        return lambda f: setattr(upgrade, 'handler', f)

    def _static(self, target, request, response, filename=None):
        if filename:
            filename = self.path(target, filename)
        else:
            filename = self.path(target)

        typ_, encoding = mimetypes.guess_type(filename)
        response.headers['Content-Type'] = typ_ or 'text/plain'
        if encoding:
            response.headers['Content-Encoding'] = encoding

        try:
            fh = open(filename)
        except:
            # TODO:
            raise response.HTTP404

        while True:
            data = fh.read(16*1024)
            if not data:
                break
            response.send(data)
            # give other coroutines a chance to run
            self.hub.sleep(0)

        fh.close()

    def static(self, path, target):
        if os.path.isdir(self.path(target)):
            self.routes.connect(
                '%s/{filename:.*?}' % path,
                f=functools.partial(self._static, target),
                conditions={'method': ['GET']})
        else:
            self.routes.connect(
                path,
                f=functools.partial(self._static, target),
                conditions={'method': ['GET']})
