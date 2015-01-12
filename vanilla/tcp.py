import socket
import errno

import vanilla.exception
import vanilla.poll


class __plugin__(object):
    def __init__(self, hub):
        self.hub = hub

    def listen(self, port=0, host='127.0.0.1'):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((host, port))
        sock.listen(socket.SOMAXCONN)
        sock.setblocking(0)
        port = sock.getsockname()[1]
        server = self.hub.register(sock.fileno(), vanilla.poll.POLLIN)

        @server.pipe
        def server(upstream, downstream):
            for mask in upstream:
                while True:
                    try:
                        conn, host = sock.accept()
                        downstream.send(self.hub.io.socket(conn))
                    except (socket.error, OSError), e:
                        if e.errno == errno.EAGAIN:
                            break
                        raise
            self.hub.unregister(sock.fileno())
            sock.close()

        server.port = port
        return server

    def connect(self, port, host='127.0.0.1'):
        conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        # TODO: this shouldn't block on the connect
        conn.connect((host, port))
        return self.hub.io.socket(conn)
