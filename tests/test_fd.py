import struct
import cffi
import os


import pytest


ffi = cffi.FFI()

ffi.cdef("""
    int eventfd(unsigned int initval, int flags);
""")

libc = ffi.dlopen("c")


class EAGAIN(Exception):
    pass


class FD(object):
    def __init__(self, fd):
        self.fd = fd

    def read(self, n=None):
        try:
            return os.read(self.fd, max(n, 4096))
        except OSError, e:
            if e.errno == 11:
                raise EAGAIN('Resource temporarily unavailable')

    def write(self, s):
        os.write(self.fd, s)


class Event(object):
    def __init__(self):
        self.fd = FD(libc.eventfd(0, os.O_NONBLOCK))

    def set(self):
        self.fd.write(struct.pack('q', 1))

    def is_set(self):
        try:
            self.fd.read()
        except EAGAIN:
            return False
        return True

    def wait(self):
        try:
            self.fd.read()
        except EAGAIN:
            return


def test_eventfd():
    event = Event()
    assert not event.is_set()
    event.set()
    assert event.is_set()
