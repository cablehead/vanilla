=================
API Documentation
=================

.. testsetup::

   import vanilla
   h = vanilla.Hub()

Hub
===

.. autoclass:: vanilla.core.Hub

Concurrency
-----------

.. automethod:: vanilla.core.Hub.spawn

.. automethod:: vanilla.core.Hub.spawn_later

.. automethod:: vanilla.core.Hub.sleep

Message Passing
---------------

.. automethod:: vanilla.core.Hub.pipe

.. automethod:: vanilla.core.Hub.select

.. automethod:: vanilla.core.Hub.dealer

.. automethod:: vanilla.core.Hub.router

.. automethod:: vanilla.core.Hub.queue

.. automethod:: vanilla.core.Hub.channel

Pipe Conveniences
-----------------

.. automethod:: vanilla.core.Hub.producer

.. automethod:: vanilla.core.Hub.pulse

TCP
---

.. py:method:: Hub.tcp.listen(port=0, host='127.0.0.1')

   Creates a TCP Listen on *host* and *port*. If *port* is 0, it will listen on
   a randomonly available port. Returns a `Recver`_ which dispenses TCP
   Connections::

        h = vanilla.Hub()

        server = h.tcp.listen()

        @server.consume
        def echo(conn):
            for date in conn.recver:
                conn.send('Echo: ' + data)

   The Recver returned has an additional attribute *port* which is the port
   that was bound to.

.. py:method:: Hub.tcp.connect(port, host='127.0.0.1')

   Creates a TCP connection to *host* and *port* and returns a `Pair`_ of a
   `Sender`_ and `Stream`_ receiver.


Message Passing Primitives
==========================

Pair
----

.. autoclass:: vanilla.message.Pair
   :members: send, recv, pipe, map, consume, close

Sender
------

.. autoclass:: vanilla.message.Sender
   :members: send

Recver
------

.. autoclass:: vanilla.message.Recver
   :members:

Pipe
----

.. autoclass:: vanilla.message.Pipe

Dealer
------

.. autoclass:: vanilla.message.Dealer

Router
------

.. autoclass:: vanilla.message.Router

Queue
-----

.. automethod:: vanilla.message.Queue

Stream
------

.. autoclass:: vanilla.message.Stream

.. autoclass:: vanilla.message::Stream.Recver
   :members:
