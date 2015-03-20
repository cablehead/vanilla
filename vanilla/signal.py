from __future__ import absolute_import

import signal


class __plugin__(object):
    def __init__(self, hub):
        self.hub = hub
        self.p = None
        self.mapper = {}

    def start(self):
        assert not self.p
        self.p = self.hub.io.pipe()

        @self.hub.spawn
        def _():
            for data in self.p.recver:
                for x in data:
                    sig = ord(x)
                    self.mapper[sig].send(sig)
            self.p = None

    def injest(self, sig):
        if self.p:
            self.p.send(chr(sig))

    def capture(self, sig):
        if not self.p:
            self.start()

        def handler(sig, frame):
            # this is running from a preemptive callback triggered. spawn to
            # minimize the amount of code running while preempted. note this
            # means spawning needs to be atomic.
            self.hub.spawn(self.injest, sig)

        self.mapper[sig] = self.hub.broadcast()
        self.mapper[sig].onempty(self.uncapture, sig)
        signal.signal(sig, handler)

    def uncapture(self, sig):
        assert not self.mapper[sig].subscribers
        signal.signal(sig, signal.SIG_DFL)
        del self.mapper[sig]
        if not self.mapper:
            self.p.close()

    def subscribe(self, *signals):
        router = self.hub.router()
        for sig in signals:
            if sig not in self.mapper:
                self.capture(sig)
            self.mapper[sig].subscribe().pipe(router)
        return router.recver
