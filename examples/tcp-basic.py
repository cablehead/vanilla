import vanilla

h = vanilla.Hub()

server = h.tcp.listen()

print("Listening on port: {0}".format(server.port))

for conn in server:
    conn.send('Hi\n')
    conn.close()
