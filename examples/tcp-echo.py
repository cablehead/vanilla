import vanilla

h = vanilla.Hub()

server = h.tcp.listen()

print("Listening on port: {0}".format(server.port))


@server.consume
def echo(conn):
    for data in conn.recver:
        conn.send(data)

h.stop_on_term()
