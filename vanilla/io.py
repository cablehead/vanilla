import socket
import fcntl
import errno
import ssl
import os

import vanilla.exception
import vanilla.message
import vanilla.poll


class __plugin__(object):
    def __init__(self, hub):
        self.hub = hub

    def fd_in(self, fd):
        return Recver(FD_from_fileno_in(self.hub, fd))

    def fd_out(self, fd):
        return Sender(FD_from_fileno_out(self.hub, fd))

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
        self.closed = False
        self.fileno = self.conn.fileno()
        unblock(self.fileno)
        self.pollin, self.pollout = hub.register(
            self.fileno, vanilla.poll.POLLIN, vanilla.poll.POLLOUT)

    def read(self, n):
        return self.conn.recv(n)

    def write(self, data):
        return self.conn.send(data)

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.conn.close()
        self.hub.unregister(self.fileno)


class Sender(object):
    def __init__(self, fd):
        self.fd = fd
        self.hub = fd.hub

        self.gate = self.hub.router().pipe(self.hub.state())
        self.fd.pollout.pipe(self.gate)
        self.fd.pollout.onclose(self.close)

        @self.hub.serialize
        def send(data, timeout=-1):
            # TODO: test timeout
            while True:
                try:
                    n = self.fd.write(data)
                except (socket.error, OSError), e:
                    if e.errno == errno.EAGAIN:
                        self.gate.clear().recv()
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
        self.gate.close()
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
                    if e.errno == errno.EAGAIN:
                        break
                    """
                    # TODO: investigate handling non-blocking ssl correctly
                    # perhaps SSL_set_fd() ??
                    """
                    if isinstance(e, ssl.SSLError):
                        break
                    sender.close()
                    return

                if not data:
                    sender.close()
                    return

                sender.send(data)
        sender.close()

    return vanilla.message.Stream(recver)
