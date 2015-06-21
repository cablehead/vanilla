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

.. automethod:: vanilla.core.Hub.state

Pipe Conveniences
-----------------

.. automethod:: vanilla.core.Hub.producer

.. automethod:: vanilla.core.Hub.pulse

Process
-------

.. py:method:: Hub.process.execv(args, env=None, stderrtoout=False)

    - Forks a child process using args.
    - *env* is an optional dictionary of environment variables which will
      replace the parent's environment for the child process. If not supplied
      the child will have access to the parent's environment.
    - if *stderrtoout* is *True* the child's stderr will be redirected to its
      stdout.
    - A `Child`_ object is return to interact with the child process.

Example usage::

    h = vanilla.Hub()

    child = h.process.execv(
        ['/usr/bin/env', 'grep', '--line-buffered', 'foo'])

    child.stdin.send('foo1\n')
    child.stdout.recv_partition('\n')   # foo1
    child.stdin.send('bar1\n')
    child.stdout.recv_partition('\n')   # would hang forever
    child.stdin.send('foo2\n')
    child.stdout.recv_partition('\n')   # foo2

    child.terminate()
    child.done.recv()

Child
~~~~~

.. py:attribute:: Child.stdin

    A `Sender`_ which allows you to send data to the child's stdin.

.. py:attribute:: Child.stdout

    A `Stream`_ recver which allows you to receive data from the child's
    stdout.

.. py:attribute:: Child.stderr

    A `Stream`_ recver which allows you to receive data from the child's
    stderr. Only available if *stderrtoout* is *False*.

.. py:attribute:: Child.done

    A `State`_ that will be set once the child terminates.

.. py:method:: Child.terminate()

    Sends the child a SIGTERM.

.. py:method:: Child.signal(signum)

    Sends the child *signum*.

TCP
---

.. py:method:: Hub.tcp.listen(port=0, host='127.0.0.1')

   Listens for TCP connections on *host* and *port*. If *port* is 0, it will
   listen on a randomly available port. Returns a `Recver`_ which dispenses
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

HTTPServer
~~~~~~~~~~

.. py:method:: Hub.http.listen(port=0, host='127.0.0.1')

    - Listens for HTTP connections on *host* and *port*. If *port* is 0, it will
      listen on a randomly available port.

    - Returns a `Recver`_ which dispenses HTTP connections.

    - These HTTP connections are a `Recver`_ which dispense
      `HTTPRequest`_. Note that if this is a Keep-Alive connection, it can
      dispense more than one `HTTPRequest`_.

An example server::

    import vanilla

    h = vanilla.Hub()

    def handle_connection(conn):
        for request in conn:
            request.reply(vanilla.http.Status(200), {}, "Hello")

    server = h.http.listen(8080)

    for conn in server:
        h.spawn(handle_connection, conn)

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

.. py:attribute:: Request.form

    A convenience to access form url encoded data as a dictionary. The form
    data is available as a key, value mappings. If a key is in the form more
    than once, only it's last value will be available.

.. py:attribute:: Request.form_multi

    A convenience to access form url encoded data as a dictionary. The form
    data is available as a key, list of values mappings.

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

.. py:method:: Hub.http.connect(port, host='127.0.0.1')

   Establishes a `HTTPClient`_ connection to *host* and *port* and requests a
   HTTP client connection. Note that if supported, this connection will be a
   Keep-Alive and multiple requests can be made over the same connection.

An example server with chunked transfer::

    import vanilla

    h = vanilla.Hub()


    serve = h.http.listen()

    client = h.http.connect('http://localhost:%s' % serve.port)
    response = client.get('/')


    conn = serve.recv()  # recvs http connection
    request = conn.recv()  # recvs http request + headers

    sender, recver = h.pipe()
    request.reply(vanilla.http.Status(200), {}, recver)

    response = response.recv()  # recvs the response + headers, but not the body

    sender.send('oh')
    print response.body.recv()  # 'oh'

    sender.send('hai')
    print response.body.recv()  # 'hai'

    sender.close()
    print response.body.recv()  # raises Closed

HTTPClient
~~~~~~~~~~

.. autoclass:: vanilla.http.HTTPClient()
   :members: request, get, post, put, delete, websocket
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

State
-----

.. automethod:: vanilla.message.State
