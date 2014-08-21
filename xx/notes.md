### Message Passing Primitives

#### Pipe

```
            +------+
            |      |
  send ---> | Pipe | ---> recv
            |      |
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

- Queue
- Dealer
- Router
- Channel
- Broadcast
- Value
- State

### Major Actions

- send
- recv
- connect
- pipe
- map
- consume

- TODO:
- filter

### thoughts from Dataflow and Reactive Programming Systems:

- Only want to activate a section of code if its outputs are available

- Deemphasize pipes an instead emphasize code units

- Bring back channels, they're an intuitive building block


### ways to send:

- pipe: blocks on send, can only have one recver
    - one sender, one recver

- dealer: one sender, many recvers

- tee: when all are ready, give to all

- broadcast: give to all that are ready
    - one sender, many recvers

- value: when set always ready, can broadcast updates
    - one sender, many recvers


### not sure if this is a sender or a recver .. i think recver??

- buffer: always ready until buffer is full


### ways to recv:

- pipe: as soon as this one is ready, recv
- router: many senders one recver
- gather: once all are ready, recv all


### selectable api:

- are you ready now? (recv(timeout=0)?)
- enqueue me, but don't pause
- dequeue me (called if we give up on the select)


### consider:

- what happens if there's an exception on the send side
- what happens if there's an exception on the read side
- what happens when the pipe wants to stop
- what happens when something else wants the pipe to stop
- what happens when the world stops


### http:

- client and server have a socket

- client sends requests to server ---->
    - requests can be streamed, so different requesters need to be seralized
    - once a websocket upgrade has been request, new requesters can't be allowed

- server receives requests <----

- for each request the server sends responses
    - these responses need to be seralized so they can be matched with requests
    - responses can be streamed

- the client receives responses, it assumes it receives them in the order they
  were sent

- client.request returns instream, outstreamer

    - client socket:
        - what happens if socket dies?
            - current request is broken
            - outstanding responses are broken
            - how to signal, and recover?

        - stop, only really makes sense to socket
            - prevent new requests
            - discard blocked requests
            - finish consuming current request
            - consume responses
            - done

        - recv instream -> drain to socket
            on exception, has request started?
                - if not, just carry on
                - midrequest ?, need to reset socket
                    - wait for outstanding responses
                    - reconnect

        - read socket -> pop outstreamer -> send till content; handle returns?
            on exception, consume remaining response, continue

    - ticker example

        - 1x conn to nasdaq.com
        - collector for e.g. aapl, amzn and outr
        - a collector is:
            - stream request to http socket
            - consume response on http socket
            - output parsed stream
            - this is just a oneshot function
            - if there's an exception, just fail and rerun next pulse

        - collector -> value / broadcast to connected clients
            - oneshot function again?


- server socket
    - read socket, stream of -> instreamer, outstreamer
        - send to instreamer until content
    - recv outstreams -> drain to socket
