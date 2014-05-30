
The general structure of a Vanilla program is a collection of code snippets
which run in a self contained loops. They receive input on a channel, process
the input appropriately and potentially send output on different channels.

```python

    h = vanilla.Hub()
    ch = h.channel()

    @h.spawn
    def _():
        while True:
            ch.send('tick')
            h.sleep(1000)

    for item in ch:
        print item
```

This will print a series of ticks every second, however, when you interrupt the
script it doesn't have a chance to shutdown cleanly:

    tick
    tick
    tick
    ^CTraceback (most recent call last):
      File "/home/andy/git/vanilla/vanilla.py", line 165, in __iter__
        yield self.recv()
      File "/home/andy/git/vanilla/vanilla.py", line 152, in recv
        item = self.hub.pause(timeout=timeout)
      File "/home/andy/git/vanilla/vanilla.py", line 255, in pause
        resume = self.loop.switch()
      File "/home/andy/git/vanilla/vanilla.py", line 339, in main
        time.sleep(timeout)
    KeyboardInterrupt

```python

    h = vanilla.Hub()
    ch = h.channel()

    @h.spawn
    def _():
        while True:
            ch.send('tick')
            h.sleep(1000)

    @h.spawn
    def _():
        for item in ch:
            print item

    done = h.signal.subscribe(signal.SIGINT, signal.SIGTERM)
    done.recv()
    h.signal.unsubscribe(done)
```
