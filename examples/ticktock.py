import vanilla

h = vanilla.Hub()


def beat(message):
    while True:
        print(message)
        h.sleep(1000)

h.spawn(beat, 'Tick')
h.spawn_later(500, beat, 'Tock')

h.stop_on_term()
