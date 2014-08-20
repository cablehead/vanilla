import vanilla

import json
# from pprint import pprint as p


class TestConsul(object):
    def test_connect(self):
        print
        print

        h = vanilla.Hub()

        """
        response = c.agent.service.deregister('zhub').recv()
        print response.status
        print response.headers
        print repr(response.consume())
        print
        """

        """
        response = c.agent.service.register(
            'zhub', service_id='n2', ttl='10s').recv()
        print response.status
        print response.headers
        print repr(response.consume())
        print
        """

        """
        response = c.agent.services().recv()
        print response.status
        print response.headers
        p(json.loads(response.consume()))
        print
        """

        @h.spawn
        def _():
            c = h.consul()
            index = None
            while True:
                response = c.health.checks('zhub', index=index).recv()
                print response.status
                print response.headers
                index = response.headers['X-Consul-Index']
                print
                data = json.loads(response.consume())
                for item in data:
                    print item
                print

        h.sleep(1000)

        c = h.consul()
        c.agent.check.pass_('service:n2').recv()

        h.sleep(15000)
