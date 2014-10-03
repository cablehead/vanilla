=================
API Documentation
=================

Core
====

Hub
---

.. autoclass:: vanilla.core.Hub

Concurrency
~~~~~~~~~~~

.. automethod:: vanilla.Hub.spawn

.. automethod:: vanilla.Hub.spawn_later

.. automethod:: vanilla.Hub.sleep

Message Passing
~~~~~~~~~~~~~~~

.. automethod:: vanilla.Hub.pipe

.. automethod:: vanilla.Hub.select

.. automethod:: vanilla.Hub.dealer

.. automethod:: vanilla.Hub.router

.. automethod:: vanilla.Hub.queue

.. automethod:: vanilla.Hub.channel

Pipe Conveniences
~~~~~~~~~~~~~~~~~

.. automethod:: vanilla.Hub.producer

.. automethod:: vanilla.Hub.consumer

.. automethod:: vanilla.Hub.pulse


Message Passing Primitives
==========================

Pair
----

.. autoclass:: vanilla.core.Pair
   :members:
   :undoc-members:

Sender
------

.. autoclass:: vanilla.core.Sender
   :members:
   :undoc-members:

Recver
------

.. autoclass:: vanilla.core.Recver
   :members:
   :undoc-members:

Pipe
----

Dealer
------

Router
------

Queue
------

Channel
-------
