import operator
import select
import errno


POLLIN = 1
POLLOUT = 2
POLLERR = 3


if hasattr(select, 'kqueue'):
    class Poll(object):
        def __init__(self):
            self.q = select.kqueue()

            self.to_ = {
                select.KQ_FILTER_READ: POLLIN,
                select.KQ_FILTER_WRITE: POLLOUT, }

            self.from_ = dict((v, k) for k, v in self.to_.iteritems())

        def register(self, fd, *masks):
            for mask in masks:
                event = select.kevent(
                    fd,
                    filter=self.from_[mask],
                    flags=select.KQ_EV_ADD | select.KQ_EV_CLEAR)
                self.q.control([event], 0)

        def unregister(self, fd, *masks):
            for mask in masks:
                event = select.kevent(
                    fd, filter=self.from_[mask], flags=select.KQ_EV_DELETE)
                self.q.control([event], 0)

        def poll(self, timeout=None):
            if timeout == -1:
                timeout = None
            while True:
                try:
                    events = self.q.control(None, 4, timeout)
                    break
                except OSError, err:
                    if err.errno == errno.EINTR:
                        continue
                    raise

            ret = []
            for e in events:
                if e.filter == select.KQ_FILTER_READ and e.data:
                    ret.append((e.ident, POLLIN))
                if e.filter == select.KQ_FILTER_WRITE:
                    ret.append((e.ident, POLLOUT))
                if e.flags & (select.KQ_EV_EOF | select.KQ_EV_ERROR):
                    ret.append((e.ident, POLLERR))
            return ret


elif hasattr(select, 'epoll'):
    class Poll(object):
        def __init__(self):
            self.q = select.epoll()

            self.to_ = {
                select.EPOLLIN: POLLIN,
                select.EPOLLOUT: POLLOUT, }

            self.from_ = dict((v, k) for k, v in self.to_.iteritems())

        def register(self, fd, *masks):
            masks = [self.from_[x] for x in masks] + [
                select.EPOLLET, select.EPOLLERR, select.EPOLLHUP]
            self.q.register(fd, reduce(operator.or_, masks, 0))

        def unregister(self, fd, *masks):
            self.q.unregister(fd)

        def poll(self, timeout=-1):
            events = self.q.poll(timeout=timeout)
            ret = []
            for fd, event in events:
                for mask in self.to_:
                    if event & mask:
                        ret.append((fd, self.to_[mask]))
                if event & (select.EPOLLERR | select.EPOLLHUP):
                    ret.append((fd, POLLERR))
            return ret

else:
    raise Exception('only epoll or kqueue supported')
