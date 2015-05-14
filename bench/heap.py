import random
import heapq
import time

heaps = []


def benchmark(name, n, f):
    start = time.time()
    for i in xrange(n):
        f()
    print '%-20s %8.2f' % (name, n / (time.time() - start))


def push():
    h = []
    for i in xrange(1000):
        heapq.heappush(h, (random.random(), i))
    heaps.append(h)


def pop():
    h = heaps.pop()
    while h:
        heapq.heappop(h)


benchmark("push", 100, push)
benchmark("pop", 100, pop)

benchmark("push", 100, push)
benchmark("pop", 100, pop)

benchmark("push", 100, push)
benchmark("pop", 100, pop)
