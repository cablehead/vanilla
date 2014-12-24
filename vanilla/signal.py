import signal

import vanilla.exception


class Signal(object):
    def __init__(self, hub):
        self.hub = hub
        self.fd_r = None
        self.fd_w = None
        self.mapper = {}

    def start(self):
        pipe_r, pipe_w = C.pipe()
        self.fd_r = self.hub.poll.fileno(pipe_r)
        self.fd_w = self.hub.poll.fileno(pipe_w)

        @self.hub.spawn
        def _():
            while True:
                try:
                    data = self.fd_r.read()
                # TODO: cleanup shutdown
                except vanilla.exception.Halt:
                    break
                # TODO: add protocol to read byte at a time
                assert len(data) == 1
                sig = ord(data)
                self.mapper[sig].send(sig)

    def capture(self, sig):
        if not self.fd_r:
            self.start()

        def handler(sig, frame):
            self.fd_w.write(chr(sig))

        signal.signal(sig, handler)

    def subscribe(self, *signals):
        router = self.hub.router()

        for sig in signals:
            if sig not in self.mapper:
                self.capture(sig)
                self.mapper[sig] = self.hub.broadcast()
            self.mapper[sig].subscribe().pipe(router)

        return router.recver
