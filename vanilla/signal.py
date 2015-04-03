from __future__ import absolute_import

import signal
import os


class __plugin__(object):
    def __init__(self, hub):
        self.hub = hub
        self.fd_w = self.recver = None
        self.mapper = {}

    def start(self):
        assert not self.fd_w
        r, self.fd_w = os.pipe()
        self.recver = self.hub.io.fd_in(r)

        @self.hub.spawn
        def _():
            for data in self.recver:
                for x in data:
                    sig = ord(x)
                    self.mapper[sig].send(sig)
            self.recver.close()
            self.fd_w = self.recver = None

    def capture(self, sig):
        if not self.fd_w:
            self.start()

        def handler(sig, frame):
            # this is running from a preemptive callback triggered by the
            # interrupt, so we write directly to a file descriptor instead of
            # using an io.pipe()
            if self.fd_w:
                os.write(self.fd_w, chr(sig))

        self.mapper[sig] = self.hub.broadcast()
        self.mapper[sig].onempty(self.uncapture, sig)
        signal.signal(sig, handler)

    def uncapture(self, sig):
        assert not self.mapper[sig].subscribers
        signal.signal(sig, signal.SIG_DFL)
        del self.mapper[sig]
        if not self.mapper:
            os.close(self.fd_w)
            # give the recv side a chance to close
            self.hub.sleep(0)

    def subscribe(self, *signals):
        router = self.hub.router()
        for sig in signals:
            if sig not in self.mapper:
                self.capture(sig)
            self.mapper[sig].subscribe().pipe(router)
        return router.recver
