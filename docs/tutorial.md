
The general structure of a Vanilla program is a collection of code snippets
which run in a self contained loops. They receive input on a channel, process
the input appropriately and potentially send output on different channels.

```python

    h = vanilla.Hub()
    sender, recver = h.pipe()

    @h.spawn
    def _():
        while True:
            sender.send('tick')
            h.sleep(1000)

    for item in recver:
        print item
```

This will print a series of ticks every second, however, when you interrupt the
script it doesn't have a chance to shutdown cleanly:

    tick
    tick
    tick
    ^CTraceback (most recent call last):
      File "vanilla/vanilla.py", line 165, in __iter__
        yield self.recv()
      File "vanilla/vanilla.py", line 152, in recv
        item = self.hub.pause(timeout=timeout)
      File "vanilla/vanilla.py", line 255, in pause
        resume = self.loop.switch()
      File "vanilla/vanilla.py", line 339, in main
        time.sleep(timeout)
    KeyboardInterrupt


## Signals

You can use *hub.signal* to subscribe to system signals, which will give you a
channel you can receive on when any of the signals you are interested in fire.
A very common pattern is to subscribe to SIGTERM and SIGINT and to then block
the main thread waiting for one of them.

```python

    h = vanilla.Hub()
    sender, recver = h.pipe()

    @h.spawn
    def _():
        while True:
            sender.send('tick')
            h.sleep(1000)

    @h.spawn
    def _():
        for item in recver:
            print item

    done = h.signal.subscribe(signal.SIGINT, signal.SIGTERM)
    done.recv()
```

## Stopping services cleanly

This cleans up the KeyboardInterrupt interrupt we saw from before, but our
service is still interrupted abruptly. We cleaned up the signal subscription
manually, but the send and receive loops were aborted. Calling *hub.stop* will
initiate sending a *Stop* exception to all registered file descriptors and
scheduled tasks. This will also take care of cleaning up our signal
subscriptions.

```python

    h = vanilla.Hub()
    sender, recver = h.pipe()

    @h.spawn
    def _():
        while True:
            try:
                sender.send('tick')
                h.sleep(1000)
            except vanilla.Stop:
                break
        sender.send('sender done.')
        sender.close()

    @h.spawn
    def _():
        for item in recver:
            print item
        print 'recver done.'

    done = h.signal.subscribe(signal.SIGINT, signal.SIGTERM)
    done.recv()
    h.stop()

    print 'peace.'
```

    tick
    tick
    tick
    ^Cwriter done.
    reader done.
    peace.


This is such a common pattern that there's a convenience to do this with
*hub.stop_on_term* .

```python

    h = vanilla.Hub()
    sender, recver = h.pipe()

    @h.spawn
    def _():
        while True:
            try:
                sender.send('tick')
                h.sleep(1000)
            except vanilla.Stop:
                break
        sender.send('sender done.')
        sender.close()

    @h.spawn
    def _():
        for item in recver:
            print item
        print 'recver done.'

    h.stop_on_term()

    print 'peace.'
```
