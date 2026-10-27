"""Opt-in, IPv4 SOOD-only Pi prototype. Never opens a RAAT/TCP listener.

An AF_PACKET socket observes discovery without binding or stealing UDP 9003
from Bridge/controller. A kernel filter discards all non-SOOD traffic. Raw UDP
preserves the discovery source port; the endpoint address becomes the actual
WireGuard address. Only replies from the configured Core are delivered back to
observed local Bridge discovery sockets. No routes, firewall or DNS are edited.
"""
from __future__ import annotations

import ctypes
from collections import OrderedDict
import hashlib
import ipaddress
import json
import os
import re
from pathlib import Path
import selectors
import socket
import struct
import subprocess
import time
import uuid

CONFIG = Path('/var/lib/roondeck-remote/discovery.json')
STATUS = Path('/var/lib/pi-home/roon-discovery-status.json')
CORE_SERVICE = '00720724-5143-4a9b-abac-0e50cba674bb'
GROUP = '239.255.90.90'
# SOOD RAAT endpoint service identifier; never query or proxy the control API.
ENDPOINT_SERVICE = 'd7634b85-8190-470f-aa51-6cb5538dc1b9'
ENDPOINT_SERVICES = {ENDPOINT_SERVICE, '5e2042ad-9bc5-4508-be92-ff68f19bdc93'}


def decode(data):
    if len(data) > 4096 or data[:5] != b'SOOD\x02' or data[5:6] not in (b'Q', b'R'):
        raise ValueError('Not a supported SOOD packet')
    values = OrderedDict(); pos = 6
    while pos < len(data):
        size = data[pos]; pos += 1
        if not size or pos + size + 2 > len(data): raise ValueError('Truncated SOOD property')
        key = data[pos:pos+size].decode('utf-8'); pos += size
        size = int.from_bytes(data[pos:pos+2], 'big'); pos += 2
        if key in values: raise ValueError('Duplicate SOOD property')
        if size == 65535: values[key] = None; continue
        if pos + size > len(data): raise ValueError('Truncated SOOD value')
        values[key] = data[pos:pos+size].decode('utf-8'); pos += size
    return data[5:6], values


def encode(kind, values):
    result = bytearray(b'SOOD\x02' + kind)
    for key, value in values.items():
        key = key.encode(); raw = value.encode() if value is not None else b''
        if not 0 < len(key) <= 255 or len(raw) >= 65535: raise ValueError('Invalid SOOD field')
        result += bytes([len(key)]) + key + struct.pack('!H', len(raw) if value is not None else 65535) + raw
    if len(result) > 4096: raise ValueError('SOOD packet too large')
    return bytes(result)


def ipv4_udp(packet):
    if len(packet) < 28 or packet[0] >> 4 != 4: raise ValueError('Not IPv4')
    header = (packet[0] & 15) * 4
    total = int.from_bytes(packet[2:4], 'big')
    if header < 20 or total > len(packet) or total < header + 8 or packet[9] != 17 or int.from_bytes(packet[6:8], 'big') & 0x3fff:
        raise ValueError('Not a complete UDP datagram')
    source, target, size, _ = struct.unpack('!HHHH', packet[header:header+8])
    if size < 8 or header + size != total: raise ValueError('Invalid UDP length')
    return socket.inet_ntoa(packet[12:16]), source, socket.inet_ntoa(packet[16:20]), target, packet[header+8:total]


def udp_packet(source, source_port, target, target_port, data):
    total = 28 + len(data)
    header = struct.pack('!BBHHHBBH4s4s', 0x45, 0, total, 0, 0, 64, 17, 0, socket.inet_aton(source), socket.inet_aton(target))
    words = struct.unpack('!10H', header); checksum = sum(words)
    while checksum >> 16: checksum = (checksum & 65535) + (checksum >> 16)
    header = header[:10] + struct.pack('!H', ~checksum & 65535) + header[12:]
    return header + struct.pack('!HHHH', source_port, target_port, len(data)+8, 0) + data


def attach_filter(sock):
    """Classic BPF on SOCK_DGRAM AF_PACKET (starts at IPv4, no Ethernet header)."""
    class Instruction(ctypes.Structure):
        _fields_ = [('code', ctypes.c_ushort), ('jt', ctypes.c_ubyte), ('jf', ctypes.c_ubyte), ('k', ctypes.c_uint)]
    class Program(ctypes.Structure):
        _fields_ = [('length', ctypes.c_ushort), ('instructions', ctypes.POINTER(Instruction))]
    code = [(0x30,0,0,9), (0x15,0,6,17), (0x28,0,0,6), (0x45,4,0,0x3fff),
            (0xb1,0,0,0), (0x40,0,0,8), (0x15,0,1,0x534f4f44), (0x06,0,0,8192), (0x06,0,0,0)]
    instructions = (Instruction * len(code))(*(Instruction(*row) for row in code))
    program = Program(len(code), instructions)
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.setsockopt(sock.fileno(), socket.SOL_SOCKET, 26, ctypes.byref(program), ctypes.sizeof(program)):
        raise OSError(ctypes.get_errno(), 'Could not install the SOOD capture filter')


def ip_text(*args):
    # RoonDeck uses BusyBox ip, which does not implement iproute2's -j mode.
    return subprocess.run(['ip', '-4', *args], capture_output=True, text=True, timeout=3, check=True).stdout


def parse_addresses(text):
    result = {}; interface = ''
    for line in text.splitlines():
        match = re.match(r'\d+: ([^:@]+)(?:@[^:]+)?:', line)
        if match: interface = match[1]
        address = re.search(r'\binet (\d+\.\d+\.\d+\.\d+)/', line)
        if address and interface: result.setdefault(interface, set()).add(address[1])
    return result


def link_state(core):
    route = ip_text('route', 'get', core)
    device = re.search(r'\bdev (\S+)', route)
    source = re.search(r'\bsrc (\S+)', route)
    if not device or device[1] != 'rdremote':
        raise ValueError('The Roon Server route is not through WireGuard; discovery is waiting without changing routes.')
    addresses = parse_addresses(ip_text('addr', 'show'))
    vpn = source[1] if source else ''
    if vpn not in addresses.get('rdremote', set()):
        raise ValueError('Waiting for a routed IPv4 WireGuard source address.')
    return vpn, set().union(*addresses.values()) if addresses else set()


class Relay:
    def __init__(self, core, vpn, own, send, clock=time.monotonic, query_local=None):
        self.core, self.vpn, self.own, self.send, self.clock = core, vpn, own, send, clock
        self.endpoints = OrderedDict(); self.seen = OrderedDict(); self.queries = OrderedDict(); self.query_local = query_local
        self.forwarded = 0; self.returned = 0; self.last_tcp_port = None

    def process(self, packet, interface):
        source, port, target, destination, data = ipv4_udp(packet)
        kind, values = decode(data); now = self.clock()
        for key in [key for key, value in self.seen.items() if now - value > 2]: self.seen.pop(key)
        signature = hashlib.sha256(packet).digest()
        if signature in self.seen: return
        self.seen[signature] = now
        while len(self.seen) > 256: self.seen.popitem(last=False)
        if source == self.core and interface == 'rdremote' and target == self.vpn:
            if kind == b'Q' and values.get('service_id') in ENDPOINT_SERVICES and self.query_local:
                transaction = values.get('_tid')
                if transaction:
                    self.queries[transaction] = (port, now)
                    self.queries.move_to_end(transaction)
                    while len(self.queries) > 128: self.queries.popitem(last=False)
                self.query_local(kind, values)
                self.returned += 1
                return
            endpoint = self.endpoints.get(destination)
            if endpoint and now - endpoint['seen'] < 180:
                reply = dict(values)
                # Keep Core identity reachable if it supplied a local override.
                if '_replyaddr' in reply: reply['_replyaddr'] = self.core
                self.send(source, port, endpoint['ip'], destination, encode(kind, reply))
                self.returned += 1
            return
        if source not in self.own or (source == self.vpn and target == self.core) or (destination != 9003 and target not in self.own and target != self.core):
            return
        if values.get('service_id') not in ENDPOINT_SERVICES or not values.get('unique_id'):
            return
        try: tcp_port = int(values.get('tcp_port', ''))
        except (TypeError, ValueError): return
        if not 1 <= tcp_port <= 65535: return
        # Different interfaces may share a discovery source port; prefer the most recently observed one.
        values['_replyaddr'] = self.vpn; values['_replyport'] = str(port)
        self.endpoints[port] = {'ip':source, 'seen':now, 'packet':encode(kind, values), 'sent':now}
        self.endpoints.move_to_end(port)
        while len(self.endpoints) > 32: self.endpoints.popitem(last=False)
        transaction = self.queries.get(values.get('_tid'))
        target_port = destination if target == self.core else transaction[0] if transaction and now - transaction[1] < 60 else 9003
        self.send(self.vpn, port, self.core, target_port, self.endpoints[port]['packet'])
        self.forwarded += 1; self.last_tcp_port = tcp_port

    def refresh(self):
        now = self.clock()
        for port, endpoint in list(self.endpoints.items()):
            if now - endpoint['seen'] >= 180: self.endpoints.pop(port); continue
            if now - endpoint['sent'] >= 15:
                self.send(self.vpn, port, self.core, 9003, endpoint['packet'])
                endpoint['sent'] = now; self.forwarded += 1


def write_status(**data):
    STATUS.parent.mkdir(parents=True, exist_ok=True)
    temporary = STATUS.with_name('.roon-discovery-' + uuid.uuid4().hex)
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(descriptor, 'w') as file:
            json.dump({'updated_at':time.time(), **data}, file)
            file.write('\n'); file.flush(); os.fchmod(file.fileno(), 0o644)
        temporary.replace(STATUS)
    finally:
        temporary.unlink(missing_ok=True)


def main():
    """OpenRC supervises the process; reconnects need no network reconfiguration."""
    while True:
        try:
            config = json.loads(CONFIG.read_text())
            if not isinstance(config, dict): raise ValueError('Invalid discovery settings; save them again in Network > VPN.')
            if config.get('enabled') is not True: return
            if json.loads(CONFIG.with_name('features.json').read_text()).get('vpn') is not True: return
            core = str(ipaddress.IPv4Address(config.get('server', '')))
            vpn, own = link_state(core)
            with socket.socket(socket.AF_PACKET, socket.SOCK_DGRAM, socket.htons(0x0800)) as capture, socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_RAW) as raw, socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
                attach_filter(capture); capture.setblocking(False)
                probe.bind(('0.0.0.0',0)); probe.setblocking(False)
                probe.setsockopt(socket.IPPROTO_IP,socket.IP_MULTICAST_TTL,1)
                def local_query(kind, values):
                    for address in own - {vpn}:
                        reply = dict(values)
                        reply['_replyaddr'] = address
                        reply['_replyport'] = str(probe.getsockname()[1])
                        try:
                            probe.setsockopt(socket.IPPROTO_IP,socket.IP_MULTICAST_IF,socket.inet_aton(address))
                            probe.sendto(encode(kind,reply),(GROUP,9003))
                        except OSError: pass
                relay = Relay(core, vpn, own, lambda src, sp, dst, dp, data: raw.sendto(udp_packet(src,sp,dst,dp,data), (dst,0)), query_local=local_query)
                with selectors.DefaultSelector() as selector:
                    selector.register(capture, selectors.EVENT_READ)
                    checked = published = 0
                    queried = float('-inf')
                    while True:
                        now = time.monotonic()
                        if now - checked >= 5:
                            checked = now
                            current = json.loads(CONFIG.read_text())
                            if current.get('enabled') is not True: return
                            if current != config or link_state(core) != (vpn, own): break
                        if now - queried >= 30:
                            queried = now
                            for service in sorted(ENDPOINT_SERVICES):
                                local_query(b'Q', {'service_id':service, '_tid':str(uuid.uuid4())})
                        # Replies are observed through AF_PACKET; drain our query socket without binding 9003.
                        for _ in range(32):
                            try: probe.recvfrom(8192)
                            except BlockingIOError: break
                        for key, _ in selector.select(1):
                            # Bounded work keeps status/reconnect checks responsive.
                            for _ in range(64):
                                try: packet, interface = key.fileobj.recvfrom(8192)
                                except BlockingIOError: break
                                try: relay.process(packet, interface[0])
                                except (ValueError, UnicodeError): continue
                        relay.refresh()
                        if now - published >= 5:
                            published = now
                            write_status(state='relaying' if relay.forwarded else 'waiting', message='Discovery packets relayed; confirm the endpoint and playback in Roon.' if relay.forwarded else 'Waiting for a local Roon Bridge announcement.', vpn_address=vpn, server=core, forwarded=relay.forwarded, replies=relay.returned, tcp_port=relay.last_tcp_port)
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            write_status(state='waiting', message=str(error)[:240], forwarded=0, replies=0)
            time.sleep(5)


if __name__ == '__main__': main()
