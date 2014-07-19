import vanilla

from vanilla import *


class Pipe(object):
    __slots__ = ['hub', 'pair']

    def __init__(self, hub):
        self.hub = hub
        self.pair = None

    def send(self, item):
        if self.pair:
            pair = self.pair
        else:
            self.pair = getcurrent()
            pair = self.hub.pause()

        self.pair = None
        self.hub.switch_to(pair, item)

    def recv(self):
        if self.pair:
            return self.hub.switch_to(self.pair, getcurrent())

        self.pair = getcurrent()
        return self.hub.pause()


# what happens if there's an exception on the send side
# what happens if there's an exception on the read side
# what happens when the pipe wants to stop
# what happens when something else wants the pipe to stop
# what happens when the world stops

def test_pipe():
    h = vanilla.Hub()

    pipe = Pipe(h)
    @h.spawn
    def _():
        for i in xrange(10):
            print "s", i
            pipe.send(i)

    print
    print
    print "-----"
    print pipe.recv()
    print
    print
    h.sleep(10)
    print "a"
    print pipe.recv()
    print "b"
