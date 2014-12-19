import operator
import select
import socket
import fcntl
import ssl
import os


POLLIN = 1
POLLOUT = 2


class __plugin__(object):
    def __init__(self, hub):
        self.hub = hub

    def pipe(self):
        r, w = os.pipe()
        recver = Recver(self.hub, FD_from_fileno(r))
        sender = Sender(self.hub, FD_from_fileno(w))
        return sender, recver


if hasattr(select, 'kqueue'):
    EAGAIN = 35

    class Poll(object):
        def __init__(self):
            self.q = select.kqueue()

            self.to_ = {
                select.KQ_FILTER_READ: POLLIN,
                select.KQ_FILTER_WRITE: POLLOUT, }

            self.from_ = dict((v, k) for k, v in self.to_.iteritems())

        def register(self, fd, *masks):
            for mask in masks:
                event = select.kevent(
                    fd, filter=self.from_[mask], flags=select.KQ_EV_ADD)
                self.q.control([event], 0)

        def unregister(self, fd, *masks):
            for mask in masks:
                event = select.kevent(
                    fd, filter=self.from_[mask], flags=select.KQ_EV_DELETE)
                self.q.control([event], 0)

        def poll(self, timeout=None):
            if timeout == -1:
                timeout = None
            events = self.q.control(None, 3, timeout)
            return [(e.ident, self.to_[e.filter]) for e in events]


elif hasattr(select, 'epoll'):
    EAGAIN = 11

    class Poll(object):
        def __init__(self):
            self.q = select.epoll()

            self.to_ = {
                select.EPOLLIN: POLLIN,
                select.EPOLLOUT: POLLOUT, }

            self.from_ = dict((v, k) for k, v in self.to_.iteritems())

        def register(self, fd, *masks):
            masks = [self.from_[x] for x in masks]
            self.q.register(fd, reduce(operator.or_, masks, 0))

        def unregister(self, fd, *masks):
            self.q.unregister(fd)

        def poll(self, timeout=None):
            events = self.q.poll(timeout=timeout)
            for fd, event in events:
                for mask in self.to_:
                    if mask & event:
                        yield fd, self.to_[mask]

else:
    raise Exception('only epoll or kqueue supported')


def unblock(fileno):
    flags = fcntl.fcntl(fileno, fcntl.F_GETFL, 0)
    flags = flags | os.O_NONBLOCK
    fcntl.fcntl(fileno, fcntl.F_SETFL, flags)
    return fileno


class FD_from_fileno(object):
    def __init__(self, fileno):
        self.fileno = fileno
        unblock(self.fileno)

    def read(self, n):
        return os.read(self.fileno, n)

    def write(self, data):
        return os.write(self.fileno, data)

    def close(self):
        try:
            os.close(self.fd)
        except OSError:
            pass


class FD_from_socket(object):
    def __init__(self, conn):
        self.conn = conn
        self.fileno = self.conn.fileno()
        unblock(self.fileno)

    def read(self, n):
        return self.conn.recv(n)

    def write(self, data):
        return self.conn.send(data)

    def close(self):
        self.conn.close()


class Sender(object):
    def __init__(self, hub, fd):
        self.hub = hub
        self.fd = fd

    def send(self, data):
        self.fd.write(data)


class Recver(object):
    def __init__(self, hub, fd):
        self.hub = hub
        self.fd = fd

        self.p = hub.pipe()

        @hub.spawn
        def _():
            events = hub.register(fd.fileno, POLLIN)
            while True:
                event = events.recv()
                print event

    def recv(self):
        return self.fd.read(4096)

    def _init__(self, hub, d):
        self.closed = False

        self.timeout = -1
        self.line_break = '\n'

        self.events = self.hub.register(self.fileno, POLLIN, POLLOUT)

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
                    if e.errno == EAGAIN:
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
                        if e.errno == EAGAIN:
                            writer.wait().clear()
                            continue
                        self.writer.close()
                        return
                    if n == len(data):
                        break
                    data = data[n:]

        for fileno, event in self.events:
            if event & POLLIN:
                reader.trigger()

            elif event & POLLOUT:
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
