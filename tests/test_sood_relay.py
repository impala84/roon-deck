import socket
import struct
import unittest
from unittest.mock import Mock, patch
from pi_bus_time_display.sood_relay import Relay, decode, encode, ipv4_udp, udp_packet, link_state, parse_addresses, CORE_SERVICE, ENDPOINT_SERVICE

class SoodRelayTests(unittest.TestCase):
    def setUp(self):
        self.now=0; self.send=Mock()
        self.relay=Relay('198.51.100.20','192.0.2.5',{'192.0.2.5','203.0.113.5'},self.send,lambda:self.now)
        self.values={'unique_id':'real-bridge-id','service_id':ENDPOINT_SERVICE,'tcp_port':'33891','opaque':'unchanged','_replyaddr':'203.0.113.5'}
    def announcement(self, kind=b'R'):
        return udp_packet('203.0.113.5',41777,'239.255.90.90',9003,encode(kind,self.values))
    def test_codec_roundtrips_null_empty_unicode_and_unknown_fields(self):
        values={'null':None,'empty':'','unknown':'£ 日本語'}
        self.assertEqual(decode(encode(b'R',values)),(b'R',values))
    def test_codec_rejects_truncated_duplicate_and_large_packets(self):
        good=encode(b'R',{'a':'b'})
        for data in (b'',b'SOOD\x02X',good[:-1],good+good[6:],good+b'\x05x',b'SOOD\x02R'+b'x'*4100):
            with self.assertRaises(ValueError):decode(data)
    def test_announcement_uses_vpn_ip_and_preserves_identity_tcp_port_and_discovery_source_port(self):
        self.relay.process(self.announcement(),'eth0')
        source,port,target,destination,payload=self.send.call_args.args
        self.assertEqual((source,port,target,destination),('192.0.2.5',41777,'198.51.100.20',9003))
        props=decode(payload)[1]
        self.assertEqual(props,{**self.values,'_replyaddr':'192.0.2.5','_replyport':'41777'})
    def test_endpoint_announcements_in_queries_are_also_relayed(self):
        self.relay.process(self.announcement(b'Q'),'eth0');self.send.assert_called_once()
    def test_only_local_endpoint_packets_are_forwarded(self):
        for source in ('203.0.113.80','198.51.100.20','127.0.0.1'):
            packet=udp_packet(source,41777,'239.255.90.90',9003,encode(b'R',self.values))
            self.relay.process(packet,'eth0')
        for bad in ({**self.values,'service_id':CORE_SERVICE},{'query_service_id':'anything'},{**self.values,'tcp_port':'0'},{**self.values,'tcp_port':'70000'}):
            self.relay.process(udp_packet('203.0.113.5',41777,'239.255.90.90',9003,encode(b'R',bad)),'eth0')
        self.send.assert_not_called()
    def test_replies_return_to_observed_bridge_socket_and_keep_core_identity(self):
        self.relay.process(self.announcement(),'eth0');self.send.reset_mock()
        reply=encode(b'R',{'service_id':CORE_SERVICE,'_replyaddr':'wrong-address','http_port':'9100'})
        self.relay.process(udp_packet('198.51.100.20',9003,'192.0.2.5',41777,reply),'rdremote')
        src,port,dst,dp,data=self.send.call_args.args
        self.assertEqual((src,port,dst,dp),('198.51.100.20',9003,'203.0.113.5',41777))
        self.assertEqual(decode(data)[1]['_replyaddr'],'198.51.100.20')
    def test_other_peers_and_unobserved_ports_cannot_inject_packets(self):
        self.relay.process(self.announcement(),'eth0');self.send.reset_mock()
        for src,port,iface in [('198.51.100.21',41777,'rdremote'),('198.51.100.20',40000,'rdremote'),('198.51.100.20',41777,'eth0')]:
            self.relay.process(udp_packet(src,9003,'192.0.2.5',port,encode(b'R',{})),iface)
        self.send.assert_not_called()
    def test_duplicate_and_forwarded_packets_do_not_loop(self):
        packet=self.announcement();self.relay.process(packet,'eth0');self.relay.process(packet,'eth0')
        self.assertEqual(self.send.call_count,1)
        args=self.send.call_args.args;self.relay.process(udp_packet(*args),'rdremote')
        self.assertEqual(self.send.call_count,1)
    def test_refresh_is_bounded_and_stale_endpoints_expire(self):
        self.relay.process(self.announcement(),'eth0')
        self.now=14;self.relay.refresh();self.assertEqual(self.send.call_count,1)
        self.now=15;self.relay.refresh();self.assertEqual(self.send.call_count,2)
        self.now=180;self.relay.refresh();self.assertEqual(self.send.call_count,2);self.assertFalse(self.relay.endpoints)
    def test_real_core_raat_query_is_probed_locally_and_response_returns_to_its_source_port(self):
        local=Mock();self.relay.query_local=local;self.relay.own.add('127.0.0.1')
        values={'service_id':ENDPOINT_SERVICE,'_tid':'core-transaction'}
        self.relay.process(udp_packet('198.51.100.20',51765,'192.0.2.5',9003,encode(b'Q',values)),'rdremote')
        local.assert_called_once_with(b'Q',values)
        response={**self.values,'_tid':'core-transaction'}
        self.relay.process(udp_packet('127.0.0.1',41777,'127.0.0.1',40001,encode(b'R',response)),'lo')
        self.assertEqual(self.send.call_args.args[:4],('192.0.2.5',41777,'198.51.100.20',51765))
        self.assertEqual(decode(self.send.call_args.args[4])[1]['_replyaddr'],'192.0.2.5')

    def test_bridge_reply_to_core_keeps_core_query_port(self):
        self.relay.process(udp_packet('203.0.113.5',41777,'198.51.100.20',51765,encode(b'R',self.values)),'rdremote')
        self.assertEqual(self.send.call_args.args[:4],('192.0.2.5',41777,'198.51.100.20',51765))

    def test_packet_roundtrip_and_ipv4_checksum(self):
        data=udp_packet('192.0.2.5',41777,'198.51.100.20',9003,b'SOOD\x02R')
        self.assertEqual(ipv4_udp(data),('192.0.2.5',41777,'198.51.100.20',9003,b'SOOD\x02R'))
        total=sum(struct.unpack('!10H',data[:20]));total=(total&65535)+(total>>16)
        self.assertEqual(total,65535)
        for broken in (data[:-1],data[:6]+b'\x20\x00'+data[8:],data[:24]+b'\x00\x07'+data[26:]):
            with self.assertRaises(ValueError):ipv4_udp(broken)
    def test_busybox_route_and_address_output(self):
        addresses='1: lo: <UP>\n    inet 127.0.0.1/8 scope host lo\n6: rdremote: <UP>\n    inet 192.0.2.5/32 scope global rdremote\n'
        self.assertEqual(parse_addresses(addresses)['rdremote'],{'192.0.2.5'})
        with patch('pi_bus_time_display.sood_relay.ip_text',side_effect=['198.51.100.20 dev rdremote src 192.0.2.5',addresses]):
            self.assertEqual(link_state('198.51.100.20'),('192.0.2.5',{'127.0.0.1','192.0.2.5'}))
        with patch('pi_bus_time_display.sood_relay.ip_text',return_value='198.51.100.20 dev eth0 src 203.0.113.54'):
            with self.assertRaisesRegex(ValueError,'not through WireGuard'):link_state('198.51.100.20')
