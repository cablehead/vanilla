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
- gather: once all are ready, recv all


### consider:

- what happens if there's an exception on the send side
- what happens if there's an exception on the read side
- what happens when the pipe wants to stop
- what happens when something else wants the pipe to stop
- what happens when the world stops
