class Timeout(Exception):
    pass


class Halt(Exception):
    pass


class Stop(Halt):
    pass


class Closed(Halt):
    pass


class Abandoned(Halt):
    pass


# TODO: think through HTTP Exceptions
class ConnectionLost(Exception):
    pass
