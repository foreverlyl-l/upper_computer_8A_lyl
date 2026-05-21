import ipaddress
import socket
import sys
from datetime import datetime, timedelta
from pathlib import Path
BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))
from app.db import Base, SessionLocal, engine
from app.packet_ingest import ingest_device_payload
BIND_IP = '0.0.0.0'
PORT = 9000
ALLOW_NETS = ('192.168.34.0/24', '192.168.50.0/24')
BUFFER_SIZE = 65535
SOCKET_RECV_BUFFER = 1024 * 1024
PC_TIME_OFFSET = timedelta(hours=8)

def main():
    allowed_nets = [ipaddress.ip_network(net, strict=False) for net in ALLOW_NETS]
    Base.metadata.create_all(bind=engine)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, SOCKET_RECV_BUFFER)
    sock.bind((BIND_IP, PORT))
    print(f'Listening UDP on {BIND_IP}:{PORT}')
    print('Allowed source subnets: ' + ', '.join((str(net) for net in allowed_nets)))
    print('Note: this receives UDP sent to this PC/port only, not every UDP port on the LAN.')
    print('Press Ctrl+C to stop.')
    total_count = 0
    accepted_count = 0
    filtered_count = 0
    while True:
        data, (src_ip, src_port) = sock.recvfrom(BUFFER_SIZE)
        total_count += 1
        src_addr = ipaddress.ip_address(src_ip)
        if not any((src_addr in net for net in allowed_nets)):
            filtered_count += 1
            continue
        accepted_count += 1
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        text = data.decode('utf-8', errors='replace')
        hex_text = data.hex(' ')
        ingest_result = None
        ingest_error = ''
        db = SessionLocal()
        try:
            ingest_result = ingest_device_payload(db, text, source_ip=src_ip, received_at=datetime.utcnow() + PC_TIME_OFFSET)
            db.commit()
        except Exception as exc:
            db.rollback()
            ingest_error = str(exc)
        finally:
            db.close()
        print('-' * 72)
        print(f'time: {now}')
        print(f'from: {src_ip}:{src_port}')
        print(f'bytes: {len(data)}')
        print(f'count: total={total_count} accepted={accepted_count} filtered={filtered_count}')
        if ingest_result:
            print(f'ingest: event_id={ingest_result.event_id} record_id={ingest_result.record_id} type={ingest_result.event_type} action={ingest_result.action}')
        else:
            print(f'ingest_error: {ingest_error}')
        print(f'text: {text}')
        print(f'hex: {hex_text}')
if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('\nStopped.')
