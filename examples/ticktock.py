import vanilla

h = vanilla.Hub()

r = h.router()


def beat(message):
    while True:
        r.send(message)
        h.sleep(1000)

h.spawn(beat, 'Tick')
h.spawn_later(500, beat, 'Tock')

for message in r.recver:
    print(message)
