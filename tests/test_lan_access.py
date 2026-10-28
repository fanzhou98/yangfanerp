import ipaddress,unittest
from types import SimpleNamespace
import test_workflow as fixture

erp=fixture.erp
class LanAccessTests(unittest.TestCase):
    def handler(self,host,origin=None,peer='192.168.31.50',lan=True):
        h=erp.Handler.__new__(erp.Handler);h.headers={'Host':host};h.client_address=(peer,10000)
        if origin:h.headers['Origin']=origin
        h.server=SimpleNamespace(server_port=8765)
        if lan:h.server.allowed_authorities={'192.168.31.39:8765'};h.server.lan_network=ipaddress.ip_network('192.168.31.0/24')
        return h
    def test_private_interface_only_and_explicit_subnet(self):
        self.assertEqual(str(erp.lan_interface('192.168.31.39/24').network),'192.168.31.0/24')
        for value in ('0.0.0.0/0','8.8.8.8/24','127.0.0.1/8','192.168.31.39','192.168.31.0/24','192.168.31.255/24','192.168.31.39/0'):
            with self.assertRaises(ValueError):erp.lan_interface(value)
    def test_lan_host_origin_and_peer_are_restricted(self):
        self.handler('192.168.31.39:8765','http://192.168.31.39:8765').check_host()
        for h in [self.handler('evil.example:8765'),self.handler('192.168.31.39:8765','https://evil.example'),self.handler('192.168.31.39:8765',peer='192.168.32.50')]:
            with self.assertRaises(ValueError):h.check_host()
    def test_default_still_loopback_only(self):
        self.handler('127.0.0.1:8765','http://127.0.0.1:8765',peer='127.0.0.1',lan=False).check_host()
        with self.assertRaises(ValueError):self.handler('192.168.31.39:8765',lan=False).check_host()
