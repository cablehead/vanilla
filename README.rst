|Vanilla| Welcome to Vanilla!
=============================

*If Go and ZeroMQ had a baby, and that baby grew up and started dating PyPy,
and they had a baby, it might look like Vanilla.*

Overview
--------

Vanilla allows you to build concurrent software in Python. Vanilla programs are
structured around independent coroutines (greenlets) which communicate with
each other via Pipes. Pipes are similar to channels in Go programming.

There's no callback crazyness and no monkey patching. Vanilla strives to be as
explict and straightforward as possible.

Documentation
-------------

`Read the Docs`_


Here's how it looks:
--------------------

You spawn coroutines:

.. code:: python

    h = vanilla.Hub()

    def beat(message):
        while True:
            print(message)
            h.sleep(1000)

    h.spawn(beat, 'Tick')
    h.spawn_later(500, beat, 'Tock')
    # Tick / Tock / Tick / Tock

Coroutines communicate via Pipes:

.. code:: python

    h = vanilla.Hub()
    sender, recver = h.pipe()
    h.spawn(sender.send, 'Hello World')
    recver.recv()
    # 'Hello World'

Pipe-fu; inspired by reactive functional patterns, Pipes can be chained:

.. code:: python

    h = vanilla.Hub()
    p = h.pipe().map(lambda x: x*2)
    h.spawn(p.send, 4)
    p.recv()
    # 8

In Vanilla, everything is a Pipe. Here's how TCP looks:

.. code:: python

    h = vanilla.Hub()

    server = h.tcp.listen(port=9000)
    # server is a Recver which dispenses new TCP connections

    conn = server.recv()
    # conn is a Pipe you can recv and send on

    message = conn.recv()
    conn.send("Echo: " + message)

Installation
------------

Vanilla works with Python 2.6 - 2.9 and PyPy.

::

    pip install vanilla

Status
------

|Build Status|\ |Coverage Status|

.. _Read the Docs: http://vanillapy.readthedocs.org/
.. |Vanilla| image:: http://vanillapy.readthedocs.org/en/latest/_static/logo.png
.. |Build Status| image:: http://img.shields.io/travis/cablehead/vanilla.svg?style=flat-square
   :target: https://travis-ci.org/cablehead/vanilla
.. |Coverage Status| image:: http://img.shields.io/coveralls/cablehead/vanilla.svg?style=flat-square
   :target: https://coveralls.io/r/cablehead/vanilla?branch=master
