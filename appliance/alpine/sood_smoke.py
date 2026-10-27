"""Real Linux raw-UDP/filter check in an isolated loopback-only container."""
import select
import socket
from pi_bus_time_display.sood_relay import attach_filter, decode, encode, ipv4_udp, udp_packet

payload=encode(b'R',{'service_id':'fixture-endpoint','unique_id':'fixture','tcp_port':'33891'})
with socket.socket(socket.AF_PACKET,socket.SOCK_DGRAM,socket.htons(0x0800)) as capture, socket.socket(socket.AF_INET,socket.SOCK_RAW,socket.IPPROTO_RAW) as sender, socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as receiver:
    attach_filter(capture)
    receiver.bind(('127.0.0.2',0));receiver.settimeout(2)
    port=receiver.getsockname()[1]
    sender.sendto(udp_packet('198.51.100.20',9003,'127.0.0.2',port,b'not-sood'),('127.0.0.2',0))
    assert receiver.recvfrom(8192)[0]==b'not-sood'
    assert not select.select([capture],[],[],.15)[0], 'Kernel filter admitted unrelated UDP traffic'
    sender.sendto(udp_packet('198.51.100.20',9003,'127.0.0.2',port,payload),('127.0.0.2',0))
    data,source=receiver.recvfrom(8192)
    assert data==payload and source==('198.51.100.20',9003), (data,source)
    assert select.select([capture],[],[],2)[0], 'Kernel filter discarded SOOD'
    data,_=capture.recvfrom(8192)
    src,sp,dst,dp,body=ipv4_udp(data)
    assert (src,sp,dst,dp,body)==('198.51.100.20',9003,'127.0.0.2',port,payload)
    assert decode(body)[1]['unique_id']=='fixture'
print('SOOD smoke: kernel capture filter and preserved raw UDP source passed on isolated loopback; no VPN, Bridge or physical audio tested.')
