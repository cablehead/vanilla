# Organ pipe arrangement of imports; because Guido likes it

import collections
import functools
import importlib
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


__version__ = '0.0.3'


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


Pair = collections.namedtuple('Pair', ['sender', 'recver'])


class Pair(Pair):
    """
    A Pair is a tuple of a `Sender`_ and a `Recver`_. The pair only share a
    weakref to each other so unless a reference is kept to both ends, the
    remaining end will be *abandoned* and the entire pair will be garbage
    collected.

    It's possible to call methods directly on the Pair tuple. A common pattern
    though is to split up the tuple with the `Sender`_ used in one closure and
    the `Recver`_ in another::

        # create a Pipe Pair
        p = h.pipe()

        # call the Pair tuple directly
        h.spawn(p.send, '1')
        p.recv() # returns '1'

        # split the sender and recver
        sender, recver = p
        sender.send('2')
        recver.recv() # returns '2'
    """
    def send(self, item, timeout=-1):
        """
        Send an *item* on this pair. This will block unless our Rever is ready,
        either forever or until *timeout* milliseconds.
        """
        return self.sender.send(item, timeout=timeout)

    def recv(self, timeout=-1):
        """
        Receive and item from our Sender. This will block unless our Sender is
        ready, either forever or unless *timeout* milliseconds.
        """
        return self.recver.recv(timeout=timeout)

    def pipe(self, target):
        """
        Pipes are Recver to the target; see :meth:`vanilla.core.Recver.pipe`

        Returns a new Pair of our current Sender and the target's Recver.
        """
        return self._replace(recver=self.recver.pipe(target))

    def map(self, f):
        """
        Maps this Pair with *f*'; see :meth:`vanilla.core.Recver.map`

        Returns a new Pair of our current Sender and the mapped target's
        Recver.
        """
        return self._replace(recver=self.recver.map(f))

    def consume(self, f):
        """
        Consumes this Pair with *f*; see :meth:`vanilla.core.Recver.consume`.

        Returns only our Sender
        """
        self.recver.consume(f)
        return self.sender

    def connect(self, recver):
        # TODO: shouldn't this return a new Pair?
        return self.sender.connect(recver)

    def close(self):
        """
        Closes both ends of this Pair
        """
        self.sender.close()
        self.recver.close()


class Pipe(object):
    """
    ::

                 +------+
        send --> | Pipe | --> recv
                 +------+

    The most basic primitive is the Pipe. A Pipe has exactly one sender and
    exactly one recver. A Pipe has no buffering, so send and recvs will block
    until there is a corresponding send or recv.

    For example, the following code will deadlock as the sender will block,
    preventing the recv from ever being called::

        h = vanilla.Hub()
        p = h.pipe()
        p.send(1)     # deadlock
        p.recv()

    The following is OK as the send is spawned to a background green thread::

        h = vanilla.Hub()
        p = h.pipe()
        h.spawn(p.send, 1)
        p.recv()      # returns 1
    """
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

        return Pair(sender, recver)

    def on_abandoned(self, *a, **kw):
        remaining = self.recver() or self.sender()
        if remaining:
            # this is running from a preemptive callback triggered by the
            # garbage collector. we spawn the abandon clean up in order to pull
            # execution back under a green thread owned by our hub, and to
            # minimize the amount of code running while preempted. note this
            # means spawning needs to be atomic.
            self.hub.spawn(remaining.abandoned)


class End(object):
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
    __slots__ = ['middle', 'upstream']

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
        """
        Send an *item* on this pair. This will block unless our Rever is ready,
        either forever or until *timeout* milliseconds.
        """
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
        del m2.sender
        del m2.recver

        del m1.recver
        m1.recver = weakref.ref(r2, m1.on_abandoned)
        m1.recver_current = m2.recver_current

        del r1.middle
        del s2.middle

        # if we are currently a chain, return the last recver of our chain
        while True:
            if getattr(r2, 'downstream', None) is None:
                break
            r2 = r2.downstream.other
        return r2


class Recver(End):
    __slots__ = ['middle', 'downstream']

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
        """
        Receive and item from our Sender. This will block unless our Sender is
        ready, either forever or unless *timeout* milliseconds.
        """
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

    def pipe(self, target):
        """
        Pipes this Recver to *target*. *target* can either be `Sender`_ (or
        `Pair`_) or a callable.

        If *target* is a Sender, the two pairs are rewired so that sending on
        this Recver's Sender will now be directed to the target's Recver::

            sender1, recver1 = h.pipe()
            sender2, recver2 = h.pipe()

            recver1.pipe(sender2)

            h.spawn(sender1.send, 'foo')
            recver2.recv() # returns 'foo'

        If *target* is a callable, a new `Pipe`_ will be created and spliced
        between this current Recver and its Sender. The two ends of this new
        Pipe are passed to the target callable to act as upstream and
        downstream. The callable can then do any processing desired including
        filtering, mapping and duplicating packets::

            sender, recver = h.pipe()

            def pipeline(upstream, downstream):
                for i in upstream:
                    if i % 2:
                        downstream.send(i*2)

            recver.pipe(pipeline)

            @h.spawn
            def _():
                for i in xrange(10):
                    sender.send(i)

            recver.recv() # returns 2 (0 is filtered, so 1*2)
            recver.recv() # returns 6 (2 is filtered, so 3*2)
        """
        if callable(target):
            """
            Rewire:
                s1 -> m1 <- r1
            To:
                s1 -> m2 <- target(r2,  s2) -> m1 <- r1
            """
            s1 = self.other
            m1 = self.middle
            r1 = self

            s2, r2 = self.hub.pipe()
            m2 = r2.middle

            s1.middle = m2
            del m2.sender
            m2.sender = weakref.ref(s1, m2.on_abandoned)

            s2.middle = m1
            del m1.sender
            m1.sender = weakref.ref(s2, m1.on_abandoned)

            # link the two ends in the closure with a strong reference to
            # prevent them from being garbage collected if this piped section
            # is used in a chain
            r2.downstream = s2
            s2.upstream = r2

            self.hub.spawn(target, r2, s2)
            return r1

        else:
            return target.connect(self)

    def map(self, f):
        """
        *f* is a callable that takes a single argument. All values sent on this
        Recver's Sender will be passed to *f* to be transformed::

            def double(i):
                return i * 2

            sender, recver = h.pipe()
            recver.map(double)

            h.spawn(sender.send, 2)
            recver.recv() # returns 4
        """
        @self.pipe
        def recver(recver, sender):
            for item in recver:
                sender.send(f(item))
        return recver

    def consume(self, f):
        """
        Creates a sink which consumes all values for this Recver. *f* is a
        callable which takes a single argument. All values sent on this
        Recver's Sender will be passed to *f* for processing. Unlike *map*
        however consume terminates this chain::

            sender, recver = h.pipe

            @recver.consume
            def _(data):
                logging.info(data)

            sender.send('Hello') # logs 'Hello'
        """
        @self.hub.spawn
        def _():
            for item in self:
                # TODO: think through whether trapping for HALT here is a good
                # idea
                try:
                    f(item)
                except Halt:
                    self.close()
                    break


def Queue(hub, size):
    """
    ::

                 +----------+
        send --> |  Queue   |
                 | (buffer) | --> recv
                 +----------+

    A Queue may also only have exactly one sender and recver. A Queue however
    has a fifo buffer of a custom size. Sends to the Queue won't block until
    the buffer becomes full::

        h = vanilla.Hub()
        q = h.queue(1)
        q.send(1)      # safe from deadlock
        # q.send(1)    # this would deadlock however as the queue only has a
                       # buffer size of 1
        q.recv()       # returns 1
    """
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
    return Pair(upstream.sender, downstream.recver)


class Dealer(object):
    """
    ::

                 +--------+  /--> recv
        send --> | Dealer | -+
                 +--------+  \--> recv

    A Dealer has exactly one sender but can have many recvers. It has no
    buffer, so sends and recvs block until a corresponding green thread is
    ready.  Sends are round robined to waiting recvers on a first come first
    serve basis::

        h = vanilla.Hub()
        d = h.dealer()
        # d.send(1)      # this would deadlock as there are no recvers
        h.spawn(lambda: 'recv 1: %s' % d.recv())
        h.spawn(lambda: 'recv 2: %s' % d.recv())
        d.send(1)
        d.send(2)
    """
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
        return Pair(sender, recver)


class Router(object):
    """
    ::

        send --\    +--------+
                +-> | Router | --> recv
        send --/    +--------+

    A Router has exactly one recver but can have many senders. It has no
    buffer, so sends and recvs block until a corresponding thread is ready.
    Sends are accepted on a first come first servce basis::

        h = vanilla.Hub()
        r = h.router()
        h.spawn(r.send, 3)
        h.spawn(r.send, 2)
        h.spawn(r.send, 1)
        r.recv() # returns 3
        r.recv() # returns 2
        r.recv() # returns 1
    """
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
        return Pair(sender, recver)


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


class Gate(object):
    def __init__(self, hub, state=False):
        self.hub = hub
        self.pipe = hub.pipe()
        self.state = state

    def trigger(self):
        self.state = True
        if self.pipe.sender.ready:
            self.pipe.send(True)

    def wait(self, timeout=-1):
        if not self.state:
            self.pipe.recv(timeout=timeout)
        return self

    def clear(self):
        self.state = False


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
        """
        Returns a `Pipe`_ `Pair`_.
        """
        return Pipe(self)

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
                except Halt:
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
        return Dealer(self)

    def router(self):
        """
        Returns a `Router`_ `Pair`_.
        """
        return Router(self)

    def queue(self, size):
        """
        Returns a `Queue`_ `Pair`_.
        """
        return Queue(self, size)

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
        return Pair(sender, recver.pipe(self.dealer()))

    def broadcast(self):
        return Broadcast(self)

    def gate(self, state=False):
        return Gate(self, state=state)

    def value(self):
        return Value(self)

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
                return end, isinstance(end, Recver) and end.recv() or None

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
        class Adapt(object):
            def __init__(self, conn):
                self.conn = conn
                self.fd = self.conn.fileno()

            def fileno(self):
                return self.fd

            def read(self, n):
                return self.conn.recv(n)

            def write(self, data):
                return self.conn.send(data)

            def close(self):
                self.conn.close()
        return Descriptor(self.hub, Adapt(conn))

    def fileno(self, fileno):
        class Adapt(object):
            def __init__(self, fd):
                self.fd = fd

            def fileno(self):
                return self.fd

            def read(self, n):
                return os.read(self.fd, n)

            def write(self, data):
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

    def __init__(self, hub, d):
        self.hub = hub

        C.unblock(d.fileno())
        self.d = d
        self.fileno = self.d.fileno()

        self.closed = False

        self.timeout = -1
        self.line_break = '\n'

        self.events = self.hub.register(
            self.fileno,
            C.EPOLLIN | C.EPOLLOUT | C.EPOLLHUP | C.EPOLLERR | C.EPOLLET |
            C.EPOLLRDHUP)

        # TODO: if this is a read or write only file, don't set up both
        # directions
        self.read_buffer = ''
        self.reader = self.hub.pipe()
        self.writer = self.hub.pipe()

        self.hub.spawn(self.main)

    def main(self):
        @self.hub.trigger
        def reader():
            while True:
                try:
                    data = self.d.read(4096)
                except (socket.error, OSError), e:
                    if e.errno == 11:  # EAGAIN
                        break

                    # TODO: investigate handling non-blocking ssl correctly
                    # perhaps SSL_set_fd() ??
                    if isinstance(e, ssl.SSLError):
                        break
                    self.reader.close()
                    return
                if not data:
                    self.reader.close()
                    return
                self.reader.send(data)

        writer = self.hub.gate()

        @self.hub.spawn
        def _():
            for data in self.writer.recver:
                while True:
                    try:
                        n = self.d.write(data)
                    except (socket.error, OSError), e:
                        if e.errno == 11:  # EAGAIN
                            writer.wait().clear()
                            continue
                        self.writer.close()
                        return
                    if n == len(data):
                        break
                    data = data[n:]

        for fileno, event in self.events:
            if event & C.EPOLLIN:
                reader.trigger()

            elif event & C.EPOLLOUT:
                writer.trigger()

            else:
                print "YARG", self.humanize_mask(event)

        self.close()

    def read(self):
        return self.reader.recv(timeout=self.timeout)

    def write(self, data):
        return self.writer.send(data)

    # TODO: experimenting with this API
    def pipe(self, sender):
        return self.reader.pipe(sender)

    def connect(self, recver):
        return self.writer.sender.connect(recver)

    def read_bytes(self, n):
        if n == 0:
            return ''

        received = len(self.read_buffer)
        segments = [self.read_buffer]
        while received < n:
            segment = self.read()
            segments.append(segment)
            received += len(segment)

        # if we've received too much, break the last segment and return the
        # additional portion to pending
        overage = received - n
        if overage:
            self.read_buffer = segments[-1][-1*(overage):]
            segments[-1] = segments[-1][:-1*(overage)]
        else:
            self.read_buffer = ''

        return ''.join(segments)

    def read_partition(self, sep):
        received = self.read_buffer
        while True:
            keep, matched, extra = received.partition(sep)
            if matched:
                self.read_buffer = extra
                return keep
            received += self.read()

    def read_line(self):
        return self.read_partition(self.line_break)

    def close(self):
        self.closed = True
        self.reader.close()
        self.writer.close()
        self.hub.unregister(self.fileno)
        try:
            self.d.close()
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
                    data = io.BytesIO(self.fd.read_bytes(size))
                except Halt:
                    self.hub.unregister(self.fileno)
                    return
                data.readinto(C.ffi.buffer(info))
                num = info.ssi_signo
                self.mapper[num].send(num)

    def stop(self):
        raise Exception('TODO')


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

    def __init__(self, hub, url):
        self.hub = hub

        parsed = urlparse.urlsplit(url)
        assert parsed.query == ''
        assert parsed.fragment == ''

        default_port = 443 if parsed.scheme == 'https' else 80
        host, port = urllib.splitnport(parsed.netloc, default_port)

        self.socket = self.hub.tcp.connect(host=host, port=port)

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
        self.responses = self.hub.queue(10)
        self.responses.pipe(self.hub.consumer(self.reader))

    def reader(self, response):
        version, code, message = self.socket.read_line().split(' ', 2)
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
        self.socket.write(request)

        # TODO: handle chunked transfers
        if data is not None:
            request_headers['Content-Length'] = len(data)
        self.write_headers(request_headers)

        # TODO: handle chunked transfers
        if data is not None:
            self.socket.write(data)

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
            except Halt:
                return

            except Timeout:
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
            except Halt:
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
                raise Closed

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
