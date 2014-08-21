### Message Passing Primitives

#### Pipe

```
           +------+
  send --> | Pipe | --> recv
           +------+
```

The most basic primitive is the Pipe. A Pipe can have exactly one sender and
exactly one recver. A Pipe has no buffering, so send and recvs will block until
there is a corresponding send or recv.

For example, the following code will deadlock as the sender will block,
preventing the recv from ever being called:

```
    >>> h = vanilla.Hub()
    >>> p = h.pipe()
    >>> p.send(1)     # deadlock
    >>> p.recv()
```

The following is OK as the send is spawned to a background green thread:

```
    >>> h = vanilla.Hub()
    >>> p = h.pipe()
    >>> h.spawn(p.send, 1)
    >>> p.recv()
    1
```

#### Queue

```
           +----------+
  send --> |  Queue   |
           | (buffer) | --> recv
           +----------+
```

A Queue may also only have exactly one sender and recver. A Queue however has a
fifo buffer of a custom size. Sends to the Queue won't block until the buffer
becomes full.

```
    >>> h = vanilla.Hub()
    >>> q = h.queue(1)
    >>> q.send(1)      # safe from deadlock
    >>> # q.send(1)    # this would deadlock however as the queue only has a
                       # buffer size of 1
    >>> q.recv()
    1
```

#### Dealer

```
           +--------+  /--> recv
  send --> | Dealer | -+
           +--------+  \--> recv
```

A Dealer has exactly one sender but can have many recvers. It has no buffer, so
sends and recvs block until there is a corresponding thread is ready. Sends are
round robined to waiting recvers on a first come first serve basis.

```
    >>> h = vanilla.Hub()
    >>> d = h.dealer()
    >>> # d.send(1)      # this would deadlock as there are no recvers
    >>> h.spawn(lambda: 'recv 1: %s' % d.recv())
    >>> h.spawn(lambda: 'recv 2: %s' % d.recv())
    >>> d.send(1)
    >>> d.send(2)
```
