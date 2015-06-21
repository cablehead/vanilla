import threading
import os


class Oneshot(object):
    def __init__(self, h, f, a):
        pipe_r, self.pipe_w = os.pipe()
        self.recver = h.io.fd_in(pipe_r).map(self.done)
        self.t = threading.Thread(target=self.run, args=(f, a))
        self.t.start()

    def done(self, x):
        return self.result

    def run(self, f, a):
        self.result = f(*a)
        os.write(self.pipe_w, chr(1))


class __plugin__(object):
    def __init__(self, hub):
        self.hub = hub

    def call(self, f, *a):
        return Oneshot(self.hub, f, a).recver
