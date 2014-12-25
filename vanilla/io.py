import socket
import fcntl
import os

import vanilla.exception
import vanilla.message
import vanilla.poll


class __plugin__(object):
    def __init__(self, hub):
        self.hub = hub

    def pipe(self):
        r, w = os.pipe()
        recver = Recver(FD_from_fileno_in(self.hub, r))
        sender = Sender(FD_from_fileno_out(self.hub, w))
        return vanilla.message.Pair(sender, recver)

    def socket(self, conn):
        fd = FD_from_socket(self.hub, conn)
        recver = vanilla.io.Recver(fd)
        sender = vanilla.io.Sender(fd)
        return vanilla.message.Pair(sender, recver)


def unblock(fileno):
    flags = fcntl.fcntl(fileno, fcntl.F_GETFL, 0)
    flags = flags | os.O_NONBLOCK
    fcntl.fcntl(fileno, fcntl.F_SETFL, flags)
    return fileno


class FD_from_fileno_in(object):
    def __init__(self, hub, fileno):
        self.hub = hub
        self.fileno = fileno
        unblock(self.fileno)
        self.pollin = hub.register(self.fileno, vanilla.poll.POLLIN)

    def read(self, n):
        return os.read(self.fileno, n)

    def close(self):
        try:
            os.close(self.fileno)
        except OSError:
            pass
        self.hub.unregister(self.fileno)


class FD_from_fileno_out(object):
    def __init__(self, hub, fileno):
        self.hub = hub
        self.fileno = fileno
        unblock(self.fileno)
        self.pollout = hub.register(self.fileno, vanilla.poll.POLLOUT)

    def write(self, data):
        return os.write(self.fileno, data)

    def close(self):
        try:
            os.close(self.fileno)
        except OSError:
            pass
        self.hub.unregister(self.fileno)


class FD_from_socket(object):
    def __init__(self, hub, conn):
        self.hub = hub
        self.conn = conn
        self.fileno = self.conn.fileno()
        unblock(self.fileno)
        self.pollin, self.pollout = hub.register(
            self.fileno, vanilla.poll.POLLIN, vanilla.poll.POLLOUT)

    def read(self, n):
        return self.conn.recv(n)

    def write(self, data):
        return self.conn.send(data)

    def close(self):
        self.conn.close()
        self.hub.unregister(self.fileno)


class Sender(object):
    def __init__(self, fd):
        self.fd = fd
        self.hub = fd.hub

        self.pulse = self.hub.pipe()

        @self.hub.spawn
        def pulse():
            for _ in fd.pollout:
                if self.pulse.sender.ready:
                    self.pulse.send(True)
            self.close()

        @self.hub.serialize
        def send(data, timeout=-1):
            # TODO: test timeout
            while True:
                try:
                    n = self.fd.write(data)
                except (socket.error, OSError), e:
                    if e.errno == vanilla.poll.EAGAIN:
                        self.pulse.recv()
                        continue
                    self.close()
                    raise vanilla.exception.Closed()
                if n == len(data):
                    break
                data = data[n:]
        self.send = send

    def connect(self, recver):
        recver.consume(self.send)

    def close(self):
        self.fd.close()


def Recver(fd):
    hub = fd.hub
    sender, recver = hub.pipe()

    recver.onclose(fd.close)

    @hub.spawn
    def _():
        for _ in fd.pollin:
            while True:
                try:
                    data = fd.read(16384)
                except (socket.error, OSError), e:
                    if e.errno == vanilla.poll.EAGAIN:
                        break
                    """
                    # TODO: investigate handling non-blocking ssl correctly
                    # perhaps SSL_set_fd() ??
                    if isinstance(e, ssl.SSLError):
                        break
                    """
                    raise

                if not data:
                    recver.close()
                    return

                sender.send(data)

        recver.close()

    return recver

    """
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
    """
