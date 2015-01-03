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

   Listens for TCP connections on *host* and *port*. If *port* is 0, it will
   listen on a randomonly available port. Returns a `Recver`_ which dispenses
   TCP connections::

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

HTTP
----

.. py:method:: Hub.http.listen(port=0, host='127.0.0.1')

    Listens for HTTP connections on *host* and *port*. If *port* is 0, it will
    listen on a randomonly available port. Returns a `Recver`_ which dispenses
    HTTP Server connections. A HTTP Server connection is a `Recver`_ which
    dispenses `HTTPRequest`_. Note that if this is a Keep-Alive connection, it
    can dispense more than one `HTTPRequest`_.

HTTPRequest
~~~~~~~~~~~

A HTTP Request is a namedtuple with the following ordered items / attributes:

.. py:attribute:: Request.method

   The HTTP request method e.g. 'GET', 'POST', 'PUT', 'DELETE', ...

.. py:attribute:: Request.path

   The path requested

.. py:attribute:: Request.version

   The HTTP version of the request

.. py:attribute:: Request.headers

   A dictionary like interface to HTTP request headers. Keys are case
   insensitive.

.. py:attribute:: Request.body

   A `Recver`_ which yields the request's body. If the Transfer-Encoding is
   chunked the entire body could be yielded over a period of time with
   successive receives.

A HTTP Request also has three methods:

.. py:method:: Request.consume()

   Blocks until the entire request body has been received and returns it as a
   single string.

.. py:method:: Request.reply(status, headers, body)

   Initiates a reply to this HTTP request. *status* is a tuple of (HTTP Code,
   message), for example (200, 'OK'). *headers* is a dictionary like interface
   to the HTTP headers to respond with. *body* can either be a string, in which
   case this response will be completed immediately. Otherwise, *body* can be a
   `Recver`_ which can have a series of strings sent, before being closed to
   indicated the response has completed. There's no need to set Content-Length
   or Transfer-Encoding in the response headers, this will be inferred
   depending on whether *body* is a string or a `Recver`_.

.. py:method:: Request.upgrade()

    If this is a request to establish a `Websocket`_, the server can call this
    method to upgrade this connection. This method returns a `Websocket`_, and
    this connection can no longer be used as a HTTP connection.

An example server::

    h = vanilla.Hub()

    serve = h.http.listen()

    @serve.consume
    def _(conn):
        for request in conn:
            # expects a path like /3
            t = int(request.path[1:])

            # initiate the response. we create a pipe in order to stream the
            # body of the response.
            sender, recver = h.pipe()
            request.reply(vanilla.http.Status(200), {}, recver)

            # for the number of times indicated in the path, transmit a string
            # and sleep half a second
            for i in xrange(t):
                sender.send(str(i))
                h.sleep(500)

            # finally, close the body to indicate the response has finished
            sender.close()

.. py:method:: Hub.http.connect(port, host='127.0.0.1')

   Establishes a `HTTPClient`_ connection to *host* and *port* and requests a
   HTTP client connection. Note that if supported, this connection will be a
   Keep-Alive and multiple requests can be made over the same connection.

HTTPClient
~~~~~~~~~~

.. autoclass:: vanilla.http.HTTPClient()
   :members: get, post, put, delete, websocket
   :undoc-members:


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
