#!/usr/bin/env python3
#  python naga_groundstation.py
import serial
import serial.tools.list_ports
import csv, os
from datetime import datetime
import firebase_admin
from firebase_admin import credentials, db

# ── แก้ตรงนี้ ─────────────────────────────────────────────────────────────────
SERVICE_ACCOUNT = "naga-cansat5454-firebase-adminsdk-fbsvc-a033a73a05.json"
DATABASE_URL    = "https://naga-cansat5454-default-rtdb.asia-southeast1.firebasedatabase.app"
SERIAL_PORT     = None
BAUD_RATE       = 115200
# ─────────────────────────────────────────────────────────────────────────────

print("🔄 กำลังเชื่อมต่อ Firebase...")
try:
    cred = credentials.Certificate(SERVICE_ACCOUNT)
    firebase_admin.initialize_app(cred, {'databaseURL': DATABASE_URL})
    ref = db.reference("/naga/latest")
    db.reference("/").get()
    print("✅ Firebase Connected!")
    print(f"   URL: {DATABASE_URL}\n")
except Exception as e:
    print(f"❌ Firebase Failed: {e}")
    exit(1)

# Packet format (จาก TX):
# TEAM04,ax,ay,az,gx,gy,gz,mx,my,mz,roll,pitch,temp,pressure,alt
FIELDS = [
    "ax", "ay", "az",
    "gx", "gy", "gz",
    "mx", "my", "mz",
    "roll", "pitch",
    "temp", "pressure", "alt"
]

LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)
log_filename = os.path.join(LOG_DIR, f"cansat_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")


def parse_line(line: str):
    line = line.strip()
    if not line:
        return None
    parts = line.split(',')

    # Format จาก RX ESP32: RSSI,TEAM04,field1,field2,...
    # Format จาก TX direct:       TEAM04,field1,field2,...
    rssi   = -999
    offset = 0

    try:
        rssi   = int(parts[0])   # มี RSSI นำหน้า
        offset = 1
    except ValueError:
        offset = 0               # ไม่มี RSSI

    # ตรวจ TEAM04 label
    if len(parts) <= offset or not parts[offset].startswith("TEAM"):
        print(f"  [WARN] ไม่พบ TEAM label: {line}")
        return None

    team   = parts[offset]
    values = parts[offset + 1:]

    if len(values) < len(FIELDS):
        print(f"  [WARN] fields={len(values)} ต้องการ {len(FIELDS)}")
        return None

    data = {
        "team":      team,
        "rssi":      rssi,
        "timestamp": datetime.utcnow().isoformat()
    }
    for i, field in enumerate(FIELDS):
        try:
            data[field] = float(values[i])
        except:
            data[field] = 0.0
    return data


def auto_detect_port():
    ports = serial.tools.list_ports.comports()
    matches = [p for p in ports if any(x in p.description for x in ['CP210', 'CH340', 'USB'])]
    if len(matches) == 1:
        print(f"[GS] Auto-detect: {matches[0].device}")
        return matches[0].device
    print("พบ ports:")
    for p in ports:
        print(f"  {p.device} — {p.description}")
    print("[ERROR] ระบุ SERIAL_PORT เช่น SERIAL_PORT = 'COM3'")
    return None


def display(data: dict, rx_count: int):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"\n{'─'*48}")
    print(f"  [{ts}] PKT #{rx_count}  TEAM: {data.get('team')}  RSSI: {data.get('rssi')} dBm")
    print(f"{'─'*48}")
    print(f"  🔄 Accelerometer (g)")
    print(f"     AX/AY/AZ : {data.get('ax',0):>7.2f} / {data.get('ay',0):>7.2f} / {data.get('az',0):>7.2f}")
    print(f"  🔄 Gyroscope (deg/s)")
    print(f"     GX/GY/GZ : {data.get('gx',0):>7.2f} / {data.get('gy',0):>7.2f} / {data.get('gz',0):>7.2f}")
    print(f"  🧲 Magnetometer (uT)")
    print(f"     MX/MY/MZ : {data.get('mx',0):>7.2f} / {data.get('my',0):>7.2f} / {data.get('mz',0):>7.2f}")
    print(f"  📐 Orientation")
    print(f"     ROLL     : {data.get('roll',0):>7.2f} °")
    print(f"     PITCH    : {data.get('pitch',0):>7.2f} °")
    print(f"  🌡  BMP280")
    print(f"     TEMP     : {data.get('temp',0):>7.2f} °C")
    print(f"     PRESSURE : {data.get('pressure',0):>9.2f} Pa")
    print(f"     ALT      : {data.get('alt',0):>7.2f} m")
    print(f"{'─'*48}")


def main():
    port = SERIAL_PORT or auto_detect_port()
    if not port:
        return

    print(f"[GS] เชื่อมต่อ {port} @ {BAUD_RATE}...")

    csv_fields = ["timestamp", "team", "rssi"] + FIELDS
    log_file = open(log_filename, 'w', newline='', encoding='utf-8')
    writer   = csv.DictWriter(log_file, fieldnames=csv_fields)
    writer.writeheader()
    print(f"[GS] Log → {log_filename}")
    print(f"[GS] พร้อมรับข้อมูล — Ctrl+C เพื่อหยุด\n")

    rx_count = 0

    try:
        with serial.Serial(port, BAUD_RATE, timeout=2) as ser:
            print("✅ Serial Connected!\n")
            while True:
                try:
                    raw = ser.readline().decode('utf-8', errors='ignore')
                except serial.SerialException as e:
                    print(f"[ERROR] {e}")
                    break

                stripped = raw.strip()
                if not stripped:
                    continue

                data = parse_line(stripped)
                if data is None:
                    print(f"  [DBG] {stripped}")
                    continue

                rx_count += 1
                display(data, rx_count)

                try:
                    ref.set(data)
                    print(f"  ✅ Firebase OK")
                except Exception as e:
                    print(f"  ❌ Firebase ERROR: {e}")

                writer.writerow({k: data.get(k, '') for k in csv_fields})
                log_file.flush()

    except KeyboardInterrupt:
        print(f"\n[GS] หยุด — รับทั้งหมด {rx_count} packets")
        print(f"[GS] Log: {log_filename}")
    except serial.SerialException as e:
        print(f"❌ Serial Error: {e}")
    finally:
        log_file.close()


if __name__ == "__main__":
    main()
