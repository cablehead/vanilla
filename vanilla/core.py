# Organ pipe arrangement of imports; because Guido likes it

from __future__ import absolute_import

import collections
import functools
import importlib
import logging
import signal
import heapq
import time


from greenlet import getcurrent
from greenlet import greenlet

import vanilla.exception
import vanilla.message
import vanilla.poll


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

        self.stopped = self.state()

        self.registered = {}
        self.poll = vanilla.poll.Poll()
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

    def state(self, state=vanilla.message.NoState):
        """
        Returns a `State`_ `Pair`_.

        *state* if supplied sets the intial state.
        """
        return vanilla.message.State(self, state=state)

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

        # TODO: rework State's is set test to be more natural
        if self.stopped.recver.ready:
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

        for fd, masks in self.registered.items():
            for mask, sender in masks.items():
                sender.stop()

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

    def dispatch_events(self, events):
        for fd, mask in events:
            if fd in self.registered:
                masks = self.registered[fd]
                if mask == vanilla.poll.POLLERR:
                    for sender in masks.values():
                        sender.close()
                else:
                    if masks[mask].ready:
                        masks[mask].send(True)

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
            try:
                events = self.poll.poll(timeout=timeout)
            # IOError from a signal interrupt
            except IOError:
                pass
            if events:
                self.spawn(self.dispatch_events, events)
