### ways to send:

- pipe: blocks on send, can only have one recver
- dealer: as soon as one is ready, give to that one, can have many recvers
- tee: when all are ready, give to all
- broadcast: give to all that are ready
- value: when set always ready, can broadcast updates


### not sure if this is a sender or a recver .. i think recver??

- buffer: always ready until buffer is full


### ways to recv:

- recv: as soon as this one is ready, recv

- router (select): as soon as one is ready, recv that one
    - everything needs to be selectable

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
            - current request is stuffed
            - outstanding responses are stuffed
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
