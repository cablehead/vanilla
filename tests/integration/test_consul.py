import vanilla

import json
import uuid

# from pprint import pprint as p

import logging
logging.basicConfig()


class TestConsul(object):
    def test_kv(self):
        h = vanilla.Hub()
        c = h.consul()

        key = uuid.uuid4().hex
        assert c.kv.get(key).recv() is None

        assert c.kv.put(key, 'bar').recv()
        index, data = c.kv.get(key).recv()
        assert data['Value'] == 'bar'
        index, data = c.kv.get(key, recurse=True).recv()
        assert [x['Value'] for x in data] == ['bar']

        assert c.kv.put(key+'1', 'bar1').recv()
        assert c.kv.put(key+'2', 'bar2').recv()
        index, data = c.kv.get(key, recurse=True).recv()
        assert sorted([x['Value'] for x in data]) == ['bar', 'bar1', 'bar2']

        assert c.kv.delete(key).recv()
        assert c.kv.get(key).recv() is None
        index, data = c.kv.get(key, recurse=True).recv()
        assert sorted([x['Value'] for x in data]) == ['bar1', 'bar2']

        assert c.kv.delete(key, recurse=True).recv()
        assert c.kv.get(key, recurse=True).recv() is None

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

        return

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
        c.agent.check.ttl_pass('service:n2').recv()

        h.sleep(15000)
