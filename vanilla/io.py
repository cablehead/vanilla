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
        recver = Recver(self.hub, FD_from_fileno(r))
        sender = Sender(self.hub, FD_from_fileno(w))
        return vanilla.message.Pair(sender, recver)


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
            os.close(self.fileno)
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
            try:
                events = hub.register(fd.fileno, vanilla.poll.POLLOUT)
            except (IOError, OSError):
                pass
            else:
                for event in events:
                    if self.pulse.sender.ready:
                        self.pulse.send(True)
            self.close()

        @hub.serialize
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
        self.hub.unregister(self.fd.fileno)


def Recver(hub, fd):
    sender, recver = hub.pipe()

    # override the Recver's close method to also close the descriptor
    _close = recver.close

    def close():
        _close()
        fd.close()
        hub.unregister(fd.fileno)

    recver.close = close

    @hub.spawn
    def _():
        try:
            events = hub.register(fd.fileno, vanilla.poll.POLLIN)
        except (IOError, OSError):
            pass
        else:
            for event in events:
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
