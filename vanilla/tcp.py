import functools
import socket

import vanilla.exception
import vanilla.poll


class TCP(object):
    def __init__(self, hub):
        self.hub = hub

    def listen(self, port=0, host='127.0.0.1', serve=None):
        if serve:
            return TCPListener(self.hub, host, port, serve)
        return functools.partial(TCPListener, self.hub, host, port)

    def connect(self, port, host='127.0.0.1'):
        conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        # TODO: this shouldn't block on the connect
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
        ready = self.hub.register(self.sock.fileno(), vanilla.poll.POLLIN)
        while True:
            try:
                ready.recv()
            except vanilla.exception.Halt:
                self.hub.unregister(self.sock.fileno())
                self.sock.close()
                return
            conn, host = self.sock.accept()
            conn = self.hub.poll.socket(conn)
            self.hub.spawn(self.serve, conn)
