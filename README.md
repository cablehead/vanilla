# ![Vanilla](docs/images/vanilla-logo.png) Welcome to Vanilla!

*If Go and ZeroMQ had a baby, and that baby grew up and started dating PyPy,
and they had a baby, it might look like Vanilla.*

## Example

```python

    h = vanilla.Hub()
    ch = h.channel()
    h.spawn(ch.send, 'Hello World')
    ch.recv()
```

## Documentation

http://cablehead.viewdocs.io/vanilla

## Acknowledgements

The Twisted Project and the entire Twisted community for the strong grounding
in [Evented Async][]. Libor Michalek and Slide Inc for showing me using [Python
coroutines][] at phenomenal scale isn't completely insane. Mike Johnson and
Fred Cheng for [Simplenote][], [Simperium][], the chance to experiment with how
apps will work with realtime APIs and for making it possible for me to live in
San Francisco. [Littleinc][] for giving me a chance to send a lot of messages
and to open source [this project][] which I started working on while there.
Justin Rosenthal for believing in me, 30% of time. Alison Kosinski, the coolest
girlfriend in the world, God and Mum.

[Evented Async]:
    http://twistedmatrix.com/documents/8.2.0/core/howto/async.html
    "Evented Async"

[Python coroutines]: https://github.com/slideinc/gogreen   "Python coroutines"
[Simplenote]:        http://simplenote.com/                "Simplenote"
[Simperium]:         https://simperium.com/                "Simperium"
[Littleinc]:         http://littleinc.com                  "Littleinc"
[this project]:      https://github.com/cablehead/vanilla  "Vanilla"
