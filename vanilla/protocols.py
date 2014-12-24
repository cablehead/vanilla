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
