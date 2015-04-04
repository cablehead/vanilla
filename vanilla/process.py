from __future__ import absolute_import


import logging
import select
import signal
import ctypes
import sys
import os

import vanilla.exception


log = logging.getLogger(__name__)


# TODO: investigate the equivalent for BSD and OSX
# TODO: should move this and poll into some kind of compat module
#
# Attempt to define a function  to ensure out children are sent a SIGTERM when
# our process dies, to avoid orphaned children.

def set_pdeathsig():
    pass

if hasattr(select, 'epoll'):
    try:
        PR_SET_PDEATHSIG = 1
        libc = ctypes.CDLL('libc.so.6')

        def set_pdeathsig():
            rc = libc.prctl(PR_SET_PDEATHSIG, signal.SIGTERM)
            assert not rc, 'PR_SET_PDEATHSIG failed: %s' % rc
    except:
        log.warn('unable to load libc: needed to set PR_SET_PDEATHSIG')


class __plugin__(object):
    def __init__(self, hub):
        self.hub = hub
        self.children = []
        self.sigchld = None

    class Child(object):
        def __init__(self, hub, pid):
            self.hub = hub
            self.pid = pid
            self.done = self.hub.state()

        def check_liveness(self):
            try:
                pid, code = os.waitpid(self.pid, os.WNOHANG)
            except OSError:
                return False

            if (pid, code) == (0, 0):
                return True

            self.exitcode = code >> 8
            self.exitsignal = code & (2**8-1)
            self.done.send(self)
            return False

        def terminate(self):
            self.signal(signal.SIGTERM)

        def signal(self, signum):
            os.kill(self.pid, signum)

    def watch(self):
        while self.children:
            try:
                self.sigchld.recv()
            except vanilla.exception.Stop:
                for child in self.children:
                    child.terminate()
                continue
            self.children = [
                child for child in self.children if child.check_liveness()]
        self.sigchld.close()

    def bootstrap(self, f, *a, **kw):
        import marshal
        import cPickle as pickle

        pipe_r, pipe_w = os.pipe()
        os.write(pipe_w, pickle.dumps((marshal.dumps(f.func_code), a, kw)))
        os.close(pipe_w)

        bootstrap = '\n'.join(x.strip() for x in ("""
            import cPickle as pickle
            import marshal
            import types
            import sys
            import os

            code, a, kw = pickle.loads(os.read(%(pipe_r)s, 4096))
            os.close(%(pipe_r)s)

            f = types.FunctionType(marshal.loads(code), globals(), 'f')
            f(*a, **kw)
        """ % {'pipe_r': pipe_r}).split('\n') if x)

        argv = [sys.executable, '-u', '-c', bootstrap]
        os.execv(argv[0], argv)

    def launch(self, f, *a, **kw):
        stderrtoout = kw.pop('stderrtoout', False)

        if not self.sigchld:
            self.sigchld = self.hub.signal.subscribe(signal.SIGCHLD)
            self.hub.spawn(self.watch)

        inpipe_r, inpipe_w = os.pipe()
        outpipe_r, outpipe_w = os.pipe()

        if not stderrtoout:
            errpipe_r, errpipe_w = os.pipe()

        pid = os.fork()

        if pid == 0:
            # child process
            set_pdeathsig()

            os.close(inpipe_w)
            os.dup2(inpipe_r, 0)
            os.close(inpipe_r)

            os.close(outpipe_r)
            os.dup2(outpipe_w, 1)

            if stderrtoout:
                os.dup2(outpipe_w, 2)
            else:
                os.close(errpipe_r)
                os.dup2(errpipe_w, 2)
                os.close(errpipe_w)

            os.close(outpipe_w)

            f(*a, **kw)
            return

        # parent continues
        os.close(inpipe_r)
        os.close(outpipe_w)

        child = self.Child(self.hub, pid)
        child.stdin = self.hub.io.fd_out(inpipe_w)
        child.stdout = self.hub.io.fd_in(outpipe_r)

        if not stderrtoout:
            os.close(errpipe_w)
            child.stderr = self.hub.io.fd_in(errpipe_r)

        self.children.append(child)
        return child

    def spawn(self, f, *a, **kw):
        return self.launch(self.bootstrap, f, *a, **kw)

    def execv(self, args, env=None, stderrtoout=False):
        if env:
            return self.launch(
                os.execve, args[0], args, env, stderrtoout=stderrtoout)
        return self.launch(os.execv, args[0], args, stderrtoout=stderrtoout)
