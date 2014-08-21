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
    >>> p.send(1)        # safe from deadlock
    >>> # p.send(1)      # this would deadlock however as the queue only has a
                         # buffer size of 1
    >>> p.recv()
    1
```
