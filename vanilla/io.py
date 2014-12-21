import socket
import fcntl
import ssl
import os

import vanilla.poll
import vanilla.core


class __plugin__(object):
    def __init__(self, hub):
        self.hub = hub

    def pipe(self):
        r, w = os.pipe()
        recver = Recver(self.hub, FD_from_fileno(r))
        sender = Sender(self.hub, FD_from_fileno(w))
        return sender, recver


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

        self.pulse = hub.pipe()

        @hub.spawn
        def pulse():
            events = hub.register(fd.fileno, vanilla.poll.POLLOUT)
            for event in events:
                if self.pulse.sender.ready:
                    self.pulse.send(True)
            print "CLOSED"

    def send(self, data):
        # TODO: serialize with a semaphore
        # TODO: test more than one write at the same time
        while True:
            try:
                n = self.fd.write(data)
            except (socket.error, OSError), e:
                if e.errno == vanilla.poll.EAGAIN:
                    self.pulse.recv()
                    continue
                raise vanilla.core.Closed()
            if n == len(data):
                break
            data = data[n:]


class Recver(object):
    def __init__(self, hub, fd):
        self.hub = hub
        self.fd = fd

        self.p = hub.pipe()

        @hub.spawn
        def _():
            events = hub.register(fd.fileno, vanilla.poll.POLLIN)
            for event in events:
                while True:
                    try:
                        data = self.fd.read(16384)
                    except (socket.error, OSError), e:
                        if e.errno == vanilla.poll.EAGAIN:
                            break
                        raise

                    if not data:
                        self.p.close()
                        return

                    self.p.send(data)

    def recv(self, timeout=-1):
        return self.p.recv(timeout=timeout)

    def _init__(self, hub, d):
        self.closed = False

        self.timeout = -1
        self.line_break = '\n'

        self.events = self.hub.register(
            self.fileno, vanilla.poll.POLLIN, vanilla.poll.POLLOUT)

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
                    if e.errno == vanilla.poll.EAGAIN:
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
                        if e.errno == vanilla.poll.EAGAIN:
                            writer.wait().clear()
                            continue
                        self.writer.close()
                        return
                    if n == len(data):
                        break
                    data = data[n:]

        for fileno, event in self.events:
            if event & vanilla.poll.POLLIN:
                reader.trigger()

            elif event & vanilla.poll.POLLOUT:
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
