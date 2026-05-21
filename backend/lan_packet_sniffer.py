from __future__ import annotations
import argparse
import contextlib
import ctypes
import ipaddress
import json
import os
import platform
import re
import signal
import socket
import struct
import subprocess
import sys
import threading
import time
from datetime import datetime
from typing import Iterable
IP_PROTOCOL_TCP = 6
IP_PROTOCOL_UDP = 17
SIO_RCVALL = getattr(socket, 'SIO_RCVALL', 2550136833)
RCVALL_ON = getattr(socket, 'RCVALL_ON', 1)
RCVALL_OFF = getattr(socket, 'RCVALL_OFF', 0)
IPCONFIG_PATH = os.path.join(os.environ.get('SystemRoot', 'C:\\Windows'), 'System32', 'ipconfig.exe')
CMD_PATH = os.path.join(os.environ.get('SystemRoot', 'C:\\Windows'), 'System32', 'cmd.exe')
POWERSHELL_PATH = os.path.join(os.environ.get('SystemRoot', 'C:\\Windows'), 'System32', 'WindowsPowerShell', 'v1.0', 'powershell.exe')
TCP_FLAG_NAMES = (('FIN', 1), ('SYN', 2), ('RST', 4), ('PSH', 8), ('ACK', 16), ('URG', 32), ('ECE', 64), ('CWR', 128))
SUBNET_MASK_LABELS = ('subnet mask', '子网掩码')
DEFAULT_GATEWAY_LABELS = ('default gateway', '默认网关')
PRINT_LOCK = threading.Lock()
COUNTER_LOCK = threading.Lock()
STOP_EVENT = threading.Event()
DEFAULT_BIND_IPS: list[str] = ['192.168.47.125']
DEFAULT_PORTS: list[int] = [8080]
DEFAULT_HIDE_PAYLOAD = False
DEFAULT_SHOW_EMPTY_PAYLOAD = False
DEFAULT_MAX_PAYLOAD_BYTES = 96
MAX_LOG_LINE_CHARS = 240
PACKET_NOTICE_PREFIX = '[RECEIVED PACKET]'
PAYLOAD_NOTICE_PREFIX = '[RECEIVED PAYLOAD]'
ATTEMPT_NOTICE_PREFIX = '[ACCESS ATTEMPT]'

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description='Capture inbound LAN TCP/UDP packets destined to this machine.')
    parser.add_argument('--bind', action='append', default=None, metavar='IP', help='Local IPv4 address to bind. Can be specified multiple times.')
    parser.add_argument('--port', action='append', type=int, default=None, metavar='PORT', help='Only show packets sent to the specified local port.')
    parser.add_argument('--hide-payload', action='store_true', default=DEFAULT_HIDE_PAYLOAD, help='Only print packet summary lines, without payload preview.')
    parser.add_argument('--show-empty-payload', action='store_true', default=DEFAULT_SHOW_EMPTY_PAYLOAD, help='Also print payload blocks for packets without payload.')
    parser.add_argument('--max-payload-bytes', type=int, default=DEFAULT_MAX_PAYLOAD_BYTES, metavar='N', help='Maximum payload bytes to print for each packet. Default: 96.')
    return parser

def ensure_windows_admin() -> None:
    if platform.system() != 'Windows':
        raise SystemExit('This script currently supports Windows only.')
    try:
        is_admin = bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        is_admin = False
    if not is_admin:
        relaunch_as_admin()

def relaunch_as_admin() -> None:
    log('Administrator privileges are required. Requesting elevation via UAC...')
    script_path = os.path.abspath(sys.argv[0])
    script_dir = os.path.dirname(script_path) or None
    python_command = subprocess.list2cmdline([sys.executable, script_path, *sys.argv[1:]])
    cmd_command = f'title LAN Packet Sniffer (Admin) && {python_command}'
    params = f'/k {cmd_command}'
    try:
        result = ctypes.windll.shell32.ShellExecuteW(None, 'runas', CMD_PATH, params, script_dir, 1)
    except Exception as exc:
        raise SystemExit(f'Failed to request administrator privileges: {exc}') from exc
    if result <= 32:
        raise SystemExit('Administrator privileges were not granted. Capture cancelled.')
    log('Elevation approved. The sniffer is continuing in a new administrator console window.')
    raise SystemExit(0)

def candidate_local_ipv4s() -> list[str]:
    adapter_networks = read_ipv4_interface_networks()
    if adapter_networks:
        return sorted(adapter_networks)
    candidates: set[str] = set()
    try:
        _, _, host_ips = socket.gethostbyname_ex(socket.gethostname())
        candidates.update(host_ips)
    except OSError:
        pass
    for target in ('192.0.2.1', '198.51.100.1', '203.0.113.1', '8.8.8.8'):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.connect((target, 80))
            candidates.add(sock.getsockname()[0])
        except OSError:
            pass
        finally:
            sock.close()
    ipconfig_output = read_ipconfig_output()
    if ipconfig_output:
        for line in ipconfig_output.splitlines():
            if 'IPv4' not in line or ':' not in line:
                continue
            maybe_ip = line.split(':')[-1].strip()
            if is_valid_ipv4(maybe_ip):
                candidates.add(maybe_ip)
    filtered = []
    for ip in sorted(candidates):
        if not is_valid_ipv4(ip):
            continue
        ip_obj = ipaddress.ip_address(ip)
        if ip_obj.is_loopback or ip_obj.is_multicast or ip_obj.is_unspecified:
            continue
        filtered.append(ip)
    return filtered

def read_ipconfig_output() -> str:
    if not os.path.isfile(IPCONFIG_PATH):
        return ''
    encodings = ('utf-8', 'gbk', 'cp936')
    for encoding in encodings:
        try:
            completed = subprocess.run([IPCONFIG_PATH], capture_output=True, text=True, encoding=encoding, errors='ignore', check=False)
            if completed.stdout:
                return completed.stdout
        except OSError:
            break
    return ''

def parse_ipconfig_interfaces() -> list[dict[str, object]]:
    output = read_ipconfig_output()
    interfaces: list[dict[str, object]] = []
    current: dict[str, object] | None = None
    for raw_line in output.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped:
            continue
        if not raw_line.startswith(' '):
            if stripped.endswith(':') and 'Windows IP Configuration' not in stripped:
                current = {'name': stripped[:-1], 'ipv4': None, 'mask': None, 'gateway': None, 'media_disconnected': False}
                interfaces.append(current)
            else:
                current = None
            continue
        if current is None:
            continue
        if ':' in stripped:
            label, value = stripped.split(':', 1)
            label = label.strip()
            value = value.strip()
            label_lower = label.lower()
            if 'media state' in label_lower and 'disconnected' in value.lower():
                current['media_disconnected'] = True
                continue
            if 'ipv4' in label_lower and is_valid_ipv4(value):
                current['ipv4'] = value
                continue
            if any((token in label_lower for token in SUBNET_MASK_LABELS)) and is_valid_ipv4(value):
                current['mask'] = value
                continue
            if any((token in label_lower for token in DEFAULT_GATEWAY_LABELS)) and is_valid_ipv4(value):
                current['gateway'] = value
                continue
            continue
        if current.get('gateway') is None and is_valid_ipv4(stripped):
            current['gateway'] = stripped
    return interfaces

def read_ipv4_interface_networks() -> dict[str, ipaddress.IPv4Network]:
    interfaces = parse_ipconfig_interfaces()
    networks: dict[str, ipaddress.IPv4Network] = {}
    for interface in interfaces:
        ipv4 = interface.get('ipv4')
        mask = interface.get('mask')
        if not ipv4 or not mask:
            continue
        if interface.get('media_disconnected'):
            continue
        try:
            network = ipaddress.IPv4Network((str(ipv4), str(mask)), strict=False)
        except ValueError:
            continue
        if network.prefixlen >= 32:
            continue
        networks[str(ipv4)] = network
    return networks

def is_valid_ipv4(value: str) -> bool:
    try:
        return isinstance(ipaddress.ip_address(value), ipaddress.IPv4Address)
    except ValueError:
        return False

def normalize_ipv4(value: str) -> str | None:
    try:
        return str(ipaddress.IPv4Address(value))
    except ipaddress.AddressValueError:
        return None

def sanitize_log_line(text: str, max_chars: int=MAX_LOG_LINE_CHARS) -> str:
    safe_chars: list[str] = []
    truncated = text[:max_chars]
    for char in truncated:
        codepoint = ord(char)
        if 32 <= codepoint <= 126:
            safe_chars.append(char)
        elif char == '\t':
            safe_chars.append(' ')
        elif codepoint <= 255:
            safe_chars.append(f'\\x{codepoint:02x}')
        else:
            safe_chars.append('?')
    if len(text) > max_chars:
        safe_chars.append(f' ... truncated {len(text) - max_chars} chars')
    return ''.join(safe_chars)

def parse_ip_header(packet: bytes) -> dict[str, object] | None:
    if len(packet) < 20:
        return None
    version_ihl, _, total_length, _, _, ttl, protocol, _, src_raw, dst_raw = struct.unpack('!BBHHHBBH4s4s', packet[:20])
    version = version_ihl >> 4
    ihl = (version_ihl & 15) * 4
    if version != 4 or ihl < 20 or len(packet) < ihl:
        return None
    if total_length == 0 or total_length > len(packet):
        total_length = len(packet)
    if total_length < ihl:
        return None
    src_ip = normalize_ipv4(socket.inet_ntoa(src_raw))
    dst_ip = normalize_ipv4(socket.inet_ntoa(dst_raw))
    if src_ip is None or dst_ip is None:
        return None
    return {'ihl': ihl, 'ttl': ttl, 'protocol': protocol, 'src_ip': src_ip, 'dst_ip': dst_ip, 'total_length': total_length}

def parse_tcp_header(segment: bytes) -> dict[str, object] | None:
    if len(segment) < 20:
        return None
    src_port, dst_port, seq, ack, offset_reserved_flags, _, _, _ = struct.unpack('!HHLLHHHH', segment[:20])
    data_offset = (offset_reserved_flags >> 12 & 15) * 4
    flags = offset_reserved_flags & 511
    if data_offset < 20 or len(segment) < data_offset:
        return None
    return {'src_port': src_port, 'dst_port': dst_port, 'seq': seq, 'ack': ack, 'header_size': data_offset, 'flags': flags}

def parse_udp_header(segment: bytes) -> dict[str, object] | None:
    if len(segment) < 8:
        return None
    src_port, dst_port, length, _checksum = struct.unpack('!HHHH', segment[:8])
    if length != 0 and length < 8:
        return None
    return {'src_port': src_port, 'dst_port': dst_port, 'length': length, 'header_size': 8}

def tcp_flags_to_text(flags: int) -> str:
    names = [name for name, mask in TCP_FLAG_NAMES if flags & mask]
    return ','.join(names) if names else 'NONE'

def format_payload_block(payload: bytes, max_bytes: int) -> str:
    shown = payload[:max_bytes]
    if not shown:
        return 'payload[0]: <empty>'
    hex_bytes = ' '.join((f'{byte:02X}' for byte in shown))
    ascii_preview = ''.join((chr(byte) if 32 <= byte <= 126 else '.' for byte in shown))
    suffix = ''
    if len(payload) > len(shown):
        suffix = f' ... truncated {len(payload) - len(shown)} bytes'
    return f'payload[{len(payload)}]: {hex_bytes}\nascii: {ascii_preview}{suffix}'

def log(message: str) -> None:
    with PRINT_LOCK:
        normalized = message.replace('\r\n', '\n').replace('\r', '\n')
        for line in normalized.split('\n'):
            print(sanitize_log_line(line), flush=True)

def prefix_multiline(text: str, prefix: str) -> str:
    return '\n'.join((f'{prefix} {line}' for line in text.splitlines()))

def log_received_packet(summary: str, payload: bytes, args: argparse.Namespace) -> None:
    log(f'{PACKET_NOTICE_PREFIX} {summary}')
    if not args.hide_payload and (payload or args.show_empty_payload):
        payload_block = format_payload_block(payload, args.max_payload_bytes)
        log(prefix_multiline(payload_block, PAYLOAD_NOTICE_PREFIX))

def protocol_name(protocol: int) -> str:
    if protocol == IP_PROTOCOL_TCP:
        return 'TCP'
    if protocol == IP_PROTOCOL_UDP:
        return 'UDP'
    return f'IPPROTO-{protocol}'

def next_attempt_counts(args: argparse.Namespace, protocol: int) -> dict[str, int]:
    with COUNTER_LOCK:
        args.packet_counts['lan_total'] += 1
        if protocol == IP_PROTOCOL_TCP:
            args.packet_counts['lan_tcp'] += 1
        elif protocol == IP_PROTOCOL_UDP:
            args.packet_counts['lan_udp'] += 1
        else:
            args.packet_counts['lan_other'] += 1
        return dict(args.packet_counts)

def log_access_attempt(src_ip: str, dst_ip: str, protocol: int, dst_port: int | None, matched_port: bool | None, packet_length: int, counts: dict[str, int], note: str | None=None) -> None:
    port_text = str(dst_port) if dst_port is not None else '-'
    if matched_port is None:
        match_text = 'n/a'
    else:
        match_text = 'yes' if matched_port else 'no'
    note_text = f' note={note}' if note else ''
    summary = f"{ATTEMPT_NOTICE_PREFIX} count={counts['lan_total']} tcp={counts['lan_tcp']} udp={counts['lan_udp']} other={counts['lan_other']} proto={protocol_name(protocol)} src={src_ip} dst={dst_ip} dst_port={port_text} matched_port={match_text} bytes={packet_length}{note_text}"
    log(summary)

def source_matches_bound_lan(src_ip: str, bind_ip: str, bind_network: ipaddress.IPv4Network | None) -> bool:
    if bind_network is None:
        return False
    try:
        src_ip_obj = ipaddress.IPv4Address(src_ip)
    except ipaddress.AddressValueError:
        return False
    if src_ip_obj.is_loopback or src_ip_obj.is_multicast or src_ip_obj.is_unspecified:
        return False
    return src_ip_obj in bind_network

def handle_packet(packet: bytes, bind_ip: str, args: argparse.Namespace) -> None:
    ip_info = parse_ip_header(packet)
    if ip_info is None:
        return
    packet = packet[:int(ip_info['total_length'])]
    dst_ip = str(ip_info['dst_ip'])
    src_ip = str(ip_info['src_ip'])
    protocol = int(ip_info['protocol'])
    bind_network = args.bind_networks.get(bind_ip)
    if dst_ip != bind_ip:
        return
    if not source_matches_bound_lan(src_ip, bind_ip, bind_network):
        return
    payload_offset = int(ip_info['ihl'])
    segment = packet[payload_offset:]
    counts = next_attempt_counts(args, protocol)
    dst_port: int | None = None
    matched_port: bool | None = None
    if protocol == IP_PROTOCOL_TCP:
        tcp_info = parse_tcp_header(segment)
        if tcp_info is None:
            log_access_attempt(src_ip, dst_ip, protocol, None, None, len(packet), counts, note='invalid_tcp_header')
            return
        dst_port = int(tcp_info['dst_port'])
        matched_port = not args.port or dst_port in args.port
        log_access_attempt(src_ip, dst_ip, protocol, dst_port, matched_port, len(packet), counts)
        if not matched_port:
            return
        payload = segment[int(tcp_info['header_size']):]
        summary = f"[{timestamp()}] TCP {src_ip}:{tcp_info['src_port']} -> {dst_ip}:{dst_port} len={len(payload)} ttl={ip_info['ttl']} flags={tcp_flags_to_text(int(tcp_info['flags']))}"
        log_received_packet(summary, payload, args)
        return
    if protocol == IP_PROTOCOL_UDP:
        udp_info = parse_udp_header(segment)
        if udp_info is None:
            log_access_attempt(src_ip, dst_ip, protocol, None, None, len(packet), counts, note='invalid_udp_header')
            return
        dst_port = int(udp_info['dst_port'])
        matched_port = not args.port or dst_port in args.port
        log_access_attempt(src_ip, dst_ip, protocol, dst_port, matched_port, len(packet), counts)
        if not matched_port:
            return
        udp_length = int(udp_info['length'])
        if udp_length == 0:
            payload = segment[int(udp_info['header_size']):]
        else:
            safe_udp_end = min(len(segment), udp_length)
            if safe_udp_end < int(udp_info['header_size']):
                return
            payload = segment[int(udp_info['header_size']):safe_udp_end]
        summary = f"[{timestamp()}] UDP {src_ip}:{udp_info['src_port']} -> {dst_ip}:{dst_port} len={len(payload)} ttl={ip_info['ttl']}"
        log_received_packet(summary, payload, args)
        return
    log_access_attempt(src_ip, dst_ip, protocol, None, None, len(packet), counts)

def timestamp() -> str:
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]

def sniff_on_interface(bind_ip: str, args: argparse.Namespace) -> None:
    sniffer = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_IP)
    sniffer.settimeout(1.0)
    try:
        try:
            sniffer.bind((bind_ip, 0))
            sniffer.setsockopt(socket.IPPROTO_IP, socket.IP_HDRINCL, 1)
            sniffer.ioctl(SIO_RCVALL, RCVALL_ON)
        except OSError as exc:
            log(f'Failed to start capture on {bind_ip}: {exc}')
            return
        log(f'Started capture on {bind_ip}')
        while not STOP_EVENT.is_set():
            try:
                packet, _address = sniffer.recvfrom(65535)
            except socket.timeout:
                continue
            except OSError as exc:
                if not STOP_EVENT.is_set():
                    log(f'Capture stopped on {bind_ip}: {exc}')
                return
            handle_packet(packet, bind_ip, args)
    finally:
        with contextlib.suppress(OSError):
            sniffer.ioctl(SIO_RCVALL, RCVALL_OFF)
        with contextlib.suppress(OSError):
            sniffer.close()
        log(f'Stopped capture on {bind_ip}')

def normalize_ports(ports: Iterable[int]) -> list[int]:
    normalized = []
    for port in ports:
        if port < 1 or port > 65535:
            raise SystemExit(f'Invalid port: {port}')
        normalized.append(port)
    return normalized

def install_signal_handlers() -> None:

    def request_stop(_signum, _frame) -> None:
        STOP_EVENT.set()
    signal.signal(signal.SIGINT, request_stop)
    if hasattr(signal, 'SIGTERM'):
        signal.signal(signal.SIGTERM, request_stop)

def read_ipv4_interface_networks_from_powershell() -> dict[str, ipaddress.IPv4Network]:
    if not os.path.isfile(POWERSHELL_PATH):
        return {}
    command = 'Get-NetIPAddress -AddressFamily IPv4 | Select-Object IPAddress,PrefixLength,SkipAsSource | ConvertTo-Json -Compress'
    try:
        completed = subprocess.run([POWERSHELL_PATH, '-NoProfile', '-Command', command], capture_output=True, text=True, encoding='utf-8', errors='ignore', check=False)
    except OSError:
        return {}
    raw = completed.stdout.strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if isinstance(data, dict):
        records = [data]
    elif isinstance(data, list):
        records = data
    else:
        return {}
    networks: dict[str, ipaddress.IPv4Network] = {}
    for record in records:
        if not isinstance(record, dict):
            continue
        ip = str(record.get('IPAddress', '')).strip()
        prefix_length = record.get('PrefixLength')
        skip_as_source = bool(record.get('SkipAsSource', False))
        if skip_as_source or not is_valid_ipv4(ip):
            continue
        try:
            prefix_length = int(prefix_length)
            network = ipaddress.IPv4Network(f'{ip}/{prefix_length}', strict=False)
        except (TypeError, ValueError):
            continue
        if network.prefixlen >= 32:
            continue
        networks[ip] = network
    return networks

def read_ipv4_interface_networks_from_route_print() -> dict[str, ipaddress.IPv4Network]:
    try:
        completed = subprocess.run(['route', 'print', '-4'], capture_output=True, text=True, encoding='utf-8', errors='ignore', check=False)
    except OSError:
        return {}
    raw = completed.stdout
    if not raw:
        return {}
    pattern = re.compile('^\\s*(\\d+\\.\\d+\\.\\d+\\.\\d+)\\s+(\\d+\\.\\d+\\.\\d+\\.\\d+)\\s+On-link\\s+(\\d+\\.\\d+\\.\\d+\\.\\d+)\\s+', re.IGNORECASE)
    networks: dict[str, ipaddress.IPv4Network] = {}
    for line in raw.splitlines():
        match = pattern.match(line)
        if not match:
            continue
        destination, mask, interface_ip = match.groups()
        if not (is_valid_ipv4(destination) and is_valid_ipv4(mask) and is_valid_ipv4(interface_ip)):
            continue
        try:
            network = ipaddress.IPv4Network((destination, mask), strict=False)
        except ValueError:
            continue
        if network.prefixlen >= 32:
            continue
        if network.network_address in (ipaddress.IPv4Address('0.0.0.0'), ipaddress.IPv4Address('224.0.0.0'), ipaddress.IPv4Address('255.255.255.255')):
            continue
        try:
            interface_ip_obj = ipaddress.IPv4Address(interface_ip)
        except ipaddress.AddressValueError:
            continue
        if interface_ip_obj not in network:
            continue
        existing = networks.get(interface_ip)
        if existing is None or network.prefixlen > existing.prefixlen:
            networks[interface_ip] = network
    return networks

def infer_private_network(bind_ip: str) -> ipaddress.IPv4Network | None:
    try:
        ip_obj = ipaddress.IPv4Address(bind_ip)
    except ipaddress.AddressValueError:
        return None
    if bind_ip.startswith('192.168.'):
        return ipaddress.IPv4Network(f'{bind_ip}/24', strict=False)
    if bind_ip.startswith('10.'):
        return ipaddress.IPv4Network(f'{bind_ip}/24', strict=False)
    if bind_ip.startswith('169.254.'):
        return ipaddress.IPv4Network(f'{bind_ip}/16', strict=False)
    if ip_obj.is_private and 16 <= ip_obj.packed[1] <= 31 and (ip_obj.packed[0] == 172):
        return ipaddress.IPv4Network(f'{bind_ip}/16', strict=False)
    return None

def build_bind_networks(bind_ips: Iterable[str], parser: argparse.ArgumentParser) -> dict[str, ipaddress.IPv4Network]:
    detected_networks = read_ipv4_interface_networks()
    detected_networks.update(read_ipv4_interface_networks_from_powershell())
    detected_networks.update(read_ipv4_interface_networks_from_route_print())
    bind_networks: dict[str, ipaddress.IPv4Network] = {}
    for bind_ip in bind_ips:
        network = detected_networks.get(bind_ip)
        if network is None:
            network = infer_private_network(bind_ip)
            if network is not None:
                log(f'Warning: subnet mask lookup failed for {bind_ip}. Falling back to inferred network {network.with_prefixlen}.')
            else:
                parser.error(f'Cannot determine subnet mask for bind IP {bind_ip}. Set DEFAULT_BIND_IPS/--bind to an IPv4 address shown by ipconfig.')
        bind_networks[bind_ip] = network
    return bind_networks

def format_bind_networks(bind_ips: Iterable[str], bind_networks: dict[str, ipaddress.IPv4Network]) -> str:
    parts = []
    for bind_ip in bind_ips:
        network = bind_networks.get(bind_ip)
        parts.append(f"{bind_ip} -> {(network.with_prefixlen if network else '<unknown>')}")
    return ', '.join(parts)

def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    args.bind = list(dict.fromkeys(args.bind or DEFAULT_BIND_IPS))
    args.port = normalize_ports(sorted(set(args.port if args.port is not None else DEFAULT_PORTS)))
    ensure_windows_admin()
    bind_ips = args.bind or candidate_local_ipv4s()
    if not bind_ips:
        parser.error('No usable local IPv4 address found. Use --bind <IP> to specify one manually.')
    invalid_bind_ips = [ip for ip in bind_ips if not is_valid_ipv4(ip)]
    if invalid_bind_ips:
        parser.error(f"Invalid --bind IPv4 address: {', '.join(invalid_bind_ips)}")
    args.bind_networks = build_bind_networks(bind_ips, parser)
    args.packet_counts = {'lan_total': 0, 'lan_tcp': 0, 'lan_udp': 0, 'lan_other': 0}
    install_signal_handlers()
    log('LAN packet sniffer is starting.')
    log(f'PID: {os.getpid()}')
    log(f"Binding to local IPv4: {', '.join(bind_ips)}")
    log(f'Bound LAN subnets: {format_bind_networks(bind_ips, args.bind_networks)}')
    if args.port:
        log(f"Filtering destination ports: {', '.join((str(port) for port in args.port))}")
    else:
        log('Filtering destination ports: all TCP/UDP ports')
    log('Source filter: same subnet as the bound local IPv4 only')
    log('Press Ctrl+C to stop.\n')
    threads = []
    for bind_ip in bind_ips:
        thread = threading.Thread(target=sniff_on_interface, args=(bind_ip, args), name=f'sniff-{bind_ip}', daemon=True)
        thread.start()
        threads.append(thread)
    try:
        while not STOP_EVENT.is_set():
            time.sleep(0.5)
            if threads and all((not thread.is_alive() for thread in threads)):
                break
    finally:
        STOP_EVENT.set()
        for thread in threads:
            thread.join(timeout=2.0)
    log('LAN packet sniffer exited.')
    return 0
if __name__ == '__main__':
    sys.exit(main())
