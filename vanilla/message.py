import collections
import weakref

from greenlet import getcurrent

import vanilla.exception


Pair = collections.namedtuple('Pair', ['sender', 'recver'])


class NoState(object):
    """a marker to indicate no state"""


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

    def clear(self):
        self.sender.clear()
        return self

    def recv(self, timeout=-1):
        """
        Receive and item from our Sender. This will block unless our Sender is
        ready, either forever or unless *timeout* milliseconds.
        """
        return self.recver.recv(timeout=timeout)

    def recv_n(self, n, timeout=-1):
        return self.recver.recv_n(n, timeout=timeout)

    def recv_partition(self, sep, timeout=-1):
        return self.recver.recv_partition(sep, timeout=timeout)

    def recv_line(self, timeout=-1):
        return self.recver.recv_line(timeout=timeout)

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

    def onclose(self, f, *a, **kw):
        self.recver.onclose(f, *a, **kw)

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
        'closed', 'closers']

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
            raise vanilla.exception.Closed
        if self.other is None:
            raise vanilla.exception.Abandoned
        return bool(self.other.current)

    def select(self):
        assert self.current is None
        self.current = getcurrent()

    def unselect(self):
        assert self.current == getcurrent()
        self.current = None

    def abandoned(self):
        if self.current:
            self.hub.throw_to(self.current, vanilla.exception.Abandoned)

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

    def onclose(self, f, *a, **kw):
        if not hasattr(self.middle, 'closers'):
            self.middle.closers = [(f, a, kw)]
        else:
            self.middle.closers.append((f, a, kw))

    def close(self, exception=vanilla.exception.Closed):
        closers = getattr(self.middle, 'closers', [])
        if closers:
            del self.middle.closers

        self.middle.closed = True

        if self.other is not None and bool(self.other.current):
            self.hub.throw_to(self.other.current, exception)

        for f, a, kw in closers:
            try:
                f(*a, **kw)
            except vanilla.exception.Halt:
                pass

    def stop(self):
        self.close(exception=vanilla.exception.Stop)


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

    def handover(self, recver):
        assert recver.ready
        recver.select()
        # switch directly, as we need to pause
        _, ret = recver.other.peak.switch(recver.other, None)
        recver.unselect()
        return ret

    def clear(self):
        self.send(NoState)

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
            return self.other.handover(self)

        return self.pause(timeout=timeout)

    def __iter__(self):
        while True:
            try:
                yield self.recv()
            except vanilla.exception.Halt:
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

        If *target* is a callable, a new `Pipe`_ will be created.  This Recver
        and the new Pipe's Sender are passed to the target callable to act as
        upstream and downstream. The callable can then do any processing
        desired including filtering, mapping and duplicating packets::

            sender, recver = h.pipe()

            def pipeline(upstream, downstream):
                for i in upstream:
                    if i % 2:
                        downstream.send(i*2)

            recver = recver.pipe(pipeline)

            @h.spawn
            def _():
                for i in xrange(10):
                    sender.send(i)

            recver.recv() # returns 2 (0 is filtered, so 1*2)
            recver.recv() # returns 6 (2 is filtered, so 3*2)
        """
        if callable(target):
            sender, recver = self.hub.pipe()

            # link the two ends in the closure with a strong reference to
            # prevent them from being garbage collected if this piped section
            # is used in a chain
            self.downstream = sender
            sender.upstream = self

            @self.hub.spawn
            def _():
                try:
                    target(self, sender)
                except vanilla.exception.Halt:
                    sender.close()

            return recver

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
                try:
                    sender.send(f(item))
                except Exception, e:
                    sender.send(e)
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
                except vanilla.exception.Halt:
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
            except vanilla.exception.Halt:
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
                self.hub.throw_to(current, vanilla.exception.Abandoned)

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
                self.hub.throw_to(current, vanilla.exception.Abandoned)

        def connect(self, recver):
            self.onclose(recver.close)
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
        self.emptiers = []

    def onempty(self, f, *a, **kw):
        self.emptiers.append((f, a, kw))

    def send(self, item):
        for subscriber in self.subscribers:
            subscriber.send(item)

    def unsubscribe(self, sender):
        self.subscribers.remove(sender)
        if not self.subscribers:
            emptiers = self.emptiers
            self.emptiers = []
            for f, a, kw in emptiers:
                f(*a, **kw)

    def subscribe(self):
        sender, recver = self.hub.pipe()
        recver.onclose(self.unsubscribe, sender)
        self.subscribers.append(sender)
        return recver

    def connect(self, recver):
        # TODO: this probably should wire onclose to recver.close
        recver.consume(self.send)


class State(object):
    """
    State is a specialized `Pipe`_ which maintains the state of a previous
    send. Sends never block, but modify the object's current state.

    When the current state is unset, a recv will block until the state is set.

    If state is set, recvs never block as well, and return the current state.

    State can cleared using the *clear* method::

        s = h.state()

        s.recv()  # this will deadlock as state is not set

        s.send(3) # sets state, note the send doesn't block even though there
                  # is no recver
        s.recv()  # 3
        s.recv()  # 3 - note subsequent recvs don't block

        s.clear() # clear the current state
        s.recv()  # this will deadlock as state is not set
    """
    class G(object):
        def __init__(self, hub, state):
            self.hub = hub
            self.state = state

        # ignore throws
        def throw(self, *a, **kw):
            self.hub.pause()

        def __nonzero__(self):
            return self.state != NoState

    class Sender(Sender):
        def init_state(self, item):
            self.current = State.G(self.hub, item)

        def send(self, item, timeout=-1):
            self.current.state = item
            if self.ready and self.current:
                return self.hub.switch_to(self.other.peak, self.other, item)

        def handover(self, recver):
            assert recver.ready
            return self.current.state

        def connect(self, recver):
            self.onclose(recver.close)
            recver.consume(self.send)
            return self.other

    def __new__(cls, hub, state=NoState):
        sender, recver = hub.pipe()
        sender.__class__ = State.Sender
        sender.init_state(state)
        return Pair(sender, recver)


class Stream(object):
    """
    A `Stream`_ is a specialized `Recver`_ which provides additional methods
    for working with streaming sources, particularly sockets and file
    descriptors.
    """
    class Recver(Recver):
        def recv(self, timeout=-1):
            if self.extra:
                extra = self.extra
                self.extra = ''
                return extra
            return super(Stream.Recver, self).recv(timeout=timeout)

        def recv_n(self, n, timeout=-1):
            """
            Blocks until *n* bytes of data are available, and then returns
            them.
            """
            got = ''
            if n:
                while len(got) < n:
                    got += self.recv(timeout=timeout)
                got, self.extra = got[:n], got[n:]
            return got

        def recv_partition(self, sep, timeout=-1):
            """
            Blocks until the seperator *sep* is seen in the stream, and then
            returns all data received until *sep*.
            """
            got = ''
            while True:
                got += self.recv(timeout=timeout)
                keep, matched, extra = got.partition(sep)
                if matched:
                    self.extra = extra
                    return keep

        def recv_line(self, timeout=-1):
            """
            Short hand to receive a line from the stream. The line seperator
            defaults to '\\n' but can be changed by setting recver.sep on this
            recver.
            """
            return self.recv_partition(self.sep, timeout=timeout)

    def __new__(cls, recver, sep='\n'):
        recver.__class__ = Stream.Recver
        recver.extra = ''
        recver.sep = sep
        return recver
