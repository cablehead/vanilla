
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


Begin demonstrating signals and clean shutdown...


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
```
