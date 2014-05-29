


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



