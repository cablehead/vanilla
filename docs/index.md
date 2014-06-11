# ![Vanilla](https://raw.githubusercontent.com/cablehead/vanilla/master/docs/images/vanilla-logo.png) Welcome to Vanilla!

> *If Go and ZeroMQ had a baby, and that baby grew up and started dating
> PyPy, and they had a baby, it might look like Vanilla.*

* [Overview](#overview)
* [Tutorial](/vanilla/tutorial)

## Example

```python

    >>> h = vanilla.Hub()
    >>> ch = h.channel()
    >>> h.spawn(ch.send, 'Hello World')
    >>> ch.recv()
    'Hello World'
```

## Overview

Vanilla is a fast, concurrent, micro server-framework. It's designed to be used
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
