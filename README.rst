|Vanilla| Welcome to Vanilla!
=============================

*If Go and ZeroMQ had a baby, and that baby grew up and started dating
PyPy, and they had a baby, it might look like Vanilla.*

|Build Status| |Coverage Status|

Example
-------

.. code:: python

    >>> h = vanilla.Hub()
    >>> sender, recver = h.pipe()
    >>> h.spawn(sender.send, 'Hello World')
    >>> recver.recv()
    'Hello World'

Documentation
-------------

`Read the Docs`_

Project Status
--------------

The current status is **experimental**. Vanilla can do a lot of interesting
things, but it's APIs, particularly it's `message passing APIs
<http://vanillapy.readthedocs.org/en/latest/api.html#pipe>`__ are under rapid
iteration. The HTTP implementation is very incomplete.

However, I think the current status is suitable for hobby projects and
it'd be great to have people using it for non-critical things to help
shape how the APIs develop!

Overview
--------

Vanilla is a fast, concurrent, micro server-library. It's designed to be
used with PyPy and with CPython 2.6 or 2.7. Vanilla is:

-  **lightweight**: requires *no* external dependencies when using PyPy.
   When using CPython you'll just need to install the Greenlet and CFFI
   packages.

-  **concurrent**: for creating highly concurrent actor based
   architectures taking inspiration from Go to use coroutines and
   message passing as core building blocks.

-  **utilitarian**: a swiss army knife for assembling services. Vanilla
   abstracts multiplexing push/pull and request/reply message passing
   patterns over TCP and UDP; signal handling; thread pools; process
   creation, control and inter-communication

-  **predictable**: Vanilla's concurrency model is based on coroutines
   or green threads, via the Greenlet package. Arguably this model
   allows a more natural and testable coding style than asynchronous
   callback models used by Twisted, Tornado and Node.

   However, green threads have been popularized in the Python world by Eventlet
   and Gevent, resulting in this model becoming synonymous with monkey
   patching. Vanilla is *strict* about *never monkey patching*, with a focus on
   being explicit and easy to reason about.

-  **pragmatic**: it let's you quickly assemble services which will run
   on Linux. But only Linux. This makes it easier to avoid introducing
   dependencies on cross platform asynchronous UI libraries like
   libevent, libev and libuv making vanilla PyPy support simple.

.. _Read the Docs: http://vanillapy.readthedocs.org/
.. |Vanilla| image:: http://vanillapy.readthedocs.org/en/latest/_static/logo.png
.. |Build Status| image:: https://travis-ci.org/cablehead/vanilla.svg?branch=master
   :target: https://travis-ci.org/cablehead/vanilla
.. |Coverage Status| image:: https://coveralls.io/repos/cablehead/vanilla/badge.png?branch=master
   :target: https://coveralls.io/r/cablehead/vanilla?branch=master
