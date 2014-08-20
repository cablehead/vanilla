# ![Vanilla](docs/images/vanilla-logo.png) Welcome to Vanilla!

*If Go and ZeroMQ had a baby, and that baby grew up and started dating PyPy,
and they had a baby, it might look like Vanilla.*

[![Build Status](https://travis-ci.org/cablehead/vanilla.svg?branch=master)](https://travis-ci.org/cablehead/vanilla) [![Coverage Status](https://coveralls.io/repos/cablehead/vanilla/badge.png?branch=rehash-pipes)](https://coveralls.io/r/cablehead/vanilla?branch=rehash-pipes)

## Example

```python

    >>> h = vanilla.Hub()
    >>> sender, recver = h.pipe()
    >>> h.spawn(sender.send, 'Hello World')
    >>> recver.recv()
    'Hello World'
```

## Overview

Vanilla is a fast, concurrent, micro server-library. It's designed to be used
with PyPy and with CPython 2.6 or 2.7. Vanilla is:

- **lightweight**: distributed as a single file and requires *no* external
  dependencies when using PyPy. When using CPython you'll just need to install
  the Greenlet and CFFI packages.

- **concurrent**: for creating highly concurrent actor based architectures
  taking inspiration from Go to use *coroutines* and *channels* for message
  passing as core building blocks.

- **utilitarian**: a swiss army knife for assembling services. Vanilla
  abstracts multiplexing push/pull and request/reply message passing patterns
  over TCP and UDP; signal handling; thread pools; process creation, control and
  inter-communication

- **predictable**: Vanilla's concurrency model is based on coroutines or green
  threads, via the Greenlet package. Arguably this model allows a more natural
  and readable coding style than asynchronous callback models used by Twisted,
  Tornado and Node.

  However, green threads have been popularized in the Python world by Eventlet
  and Gevent, resulting in this model becoming synonymous with monkey patching.
  Vanilla is *strict* about *never monkey patching*, with a focus on being
  explicit and easy to reason about.

- **pragmatic**: it let's you quickly assemble services which will run on
  Linux. But only Linux. This makes it easier to avoid introducing dependencies
  on cross platform asynchronous UI libraries like libevent, libev and libuv
  making vanilla PyPy support simple.

## Documentation

http://cablehead.viewdocs.io/vanilla

## Acknowledgements

The Twisted Project and the entire Twisted community for the strong grounding
in [Evented Async][]. Libor Michalek and Slide Inc for showing me using [Python
coroutines][] at phenomenal scale isn't completely insane. Mike Johnston and
Fred Cheng for [Simplenote][], [Simperium][], the chance to experiment with how
apps will work with realtime APIs and for making it possible for me to live in
San Francisco. [Littleinc][] for giving me a chance to send a lot of messages
and to open source [this project][] which I started working on while there.
Justin Rosenthal for believing in me, 30% of time. Andres Buritica who did a
lot of the early HTTP and UDP fragment (not pushed just yet!) work and Alison
Kosinski, the coolest fiancee in the world.

[Evented Async]:
    http://twistedmatrix.com/documents/8.2.0/core/howto/async.html
    "Evented Async"

[Python coroutines]: https://github.com/slideinc/gogreen   "Python coroutines"
[Simplenote]:        http://simplenote.com/                "Simplenote"
[Simperium]:         https://simperium.com/                "Simperium"
[Littleinc]:         http://littleinc.com                  "Littleinc"
[this project]:      https://github.com/cablehead/vanilla  "Vanilla"
