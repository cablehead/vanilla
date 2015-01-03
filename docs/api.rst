=================
API Documentation
=================

.. testsetup::

   import vanilla
   h = vanilla.Hub()

Core
====

Hub
---

.. autoclass:: vanilla.core.Hub

Concurrency
~~~~~~~~~~~

.. automethod:: vanilla.core.Hub.spawn

.. automethod:: vanilla.core.Hub.spawn_later

.. automethod:: vanilla.core.Hub.sleep

Message Passing
~~~~~~~~~~~~~~~

.. automethod:: vanilla.core.Hub.pipe

.. automethod:: vanilla.core.Hub.select

.. automethod:: vanilla.core.Hub.dealer

.. automethod:: vanilla.core.Hub.router

.. automethod:: vanilla.core.Hub.queue

.. automethod:: vanilla.core.Hub.channel

Pipe Conveniences
~~~~~~~~~~~~~~~~~

.. automethod:: vanilla.core.Hub.producer

.. automethod:: vanilla.core.Hub.pulse


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
