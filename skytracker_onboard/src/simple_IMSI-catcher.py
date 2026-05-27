#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Description:
# Passively captures IMSI and TMSI values from GSM downlinks via SDR loopback.
# Employs Scapy to unpack GSMP packets and correlates identities.
# Note: Designed for educational network auditing.

import ctypes
import json
import datetime
import io
import socket
from optparse import OptionParser

global_tracker = None

class ImsiMonitor:
    def __init__(self):
        self.active_imsis = {}
        self.imsi_list = []
        self.tmsi_map = {}
        self.imsi_count = 0

        self.mcc = ""
        self.mnc = ""
        self.lac = ""
        self.cell_id = ""
        self.country = ""
        self.brand = ""
        self.operator = ""

        self.purge_timeout_mins = 10
        self.display_all_tmsi = False
        
        self.mcc_db = None
        self.sqlite_conn = None
        self.mysql_conn = None
        self.mysql_cursor = None
        self.txt_log_path = None
        
        self.output_handler = self._default_output_formatter
        self._load_mcc_database()
        self.target_imsi = ""
        self.target_imsi_len = 0

    def set_output_handler(self, handler):
        self.output_handler = handler

    def filter_imsi(self, filter_str):
        self.target_imsi = filter_str
        self.target_imsi_len = len(filter_str)

    def _format_tmsi_hex(self, tmsi_bytes):
        if not tmsi_bytes:
            return ""
        hex_str = "0x"
        for byte in tmsi_bytes:
            encoded = hex(byte)
            if len(encoded) == 4:
                hex_str += f"{encoded[2]}{encoded[3]}"
            else:
                hex_str += f"0{encoded[2]}"
        return hex_str

    def _decode_raw_imsi(self, imsi_bytes):
        decoded = ''
        for byte in imsi_bytes:
            encoded = hex(byte)
            if len(encoded) == 4:
                decoded += f"{encoded[3]}{encoded[2]}"
            else:
                decoded += f"{encoded[2]}0"

        mcc_part = decoded[1:4]
        mnc_part = decoded[4:6]
        return decoded, mcc_part, mnc_part

    def extract_imsi_metadata(self, raw_imsi, pkt_data=""):
        decoded, mcc, mnc = self._decode_raw_imsi(raw_imsi)
        c_name, b_name, o_name = "", "", ""

        if self.mcc_db and mcc in self.mcc_db:
            if mnc in self.mcc_db[mcc]:
                b_name, o_name, c_name, _ = self.mcc_db[mcc][mnc]
                decoded = f"{mcc} {mnc} {decoded[6:]}"
            elif mnc + decoded[6:7] in self.mcc_db[mcc]:
                mnc += decoded[6:7]
                b_name, o_name, c_name, _ = self.mcc_db[mcc][mnc]
                decoded = f"{mcc} {mnc} {decoded[7:]}"
        else:
            c_name = f"Unknown MCC {mcc}"
            b_name = f"Unknown MNC {mnc}"
            o_name = f"Unknown MNC {mnc}"
            decoded = f"{mcc} {mnc} {decoded[6:]}"

        return decoded, c_name, b_name, o_name

    def _load_mcc_database(self):
        import os
        db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'mcc_codes.json')
        try:
            with io.open(db_path, 'r', encoding='utf8') as f_in:
                self.mcc_db = json.load(f_in)
        except Exception:
            self.mcc_db = {}

    def update_cell_info(self, mcc_val, mnc_val, lac_val, cell_val):
        self.mcc = str(mcc_val)
        self.mnc = str(mnc_val)
        self.lac = str(lac_val)
        self.cell_id = str(cell_val)
        
        if self.mcc_db and mcc_val in self.mcc_db and mnc_val in self.mcc_db[mcc_val]:
            self.brand, self.operator, self.country, _ = self.mcc_db[mcc_val][mnc_val]
        else:
            self.country = f"Unknown MCC {mcc_val}"
            self.brand = f"Unknown MNC {mnc_val}"
            self.operator = f"Unknown MNC {mnc_val}"

    def setup_sqlite(self, filepath):
        import sqlite3
        print(f"[*] Attaching local SQLite Database: {filepath}")
        self.sqlite_conn = sqlite3.connect(filepath)
        self.sqlite_conn.text_factory = str
        self.sqlite_conn.execute(
            "CREATE TABLE IF NOT EXISTS observations("
            "stamp datetime, tmsi1 text, tmsi2 text, imsi text, "
            "imsicountry text, imsibrand text, imsioperator text, "
            "mcc integer, mnc integer, lac integer, cell integer);"
        )

    def setup_txt_log(self, filepath):
        with open(filepath, "w") as f_out:
            f_out.write("stamp, tmsi1, tmsi2, imsi, imsicountry, imsibrand, imsioperator, mcc, mnc, lac, cell\n")
        self.txt_log_path = filepath

    def setup_mysql(self):
        import os.path
        if os.path.isfile('.env'):
            import MySQLdb as mdb
            from decouple import config
            self.mysql_conn = mdb.connect(config("MYSQL_HOST"), config("MYSQL_USER"), config("MYSQL_PASSWORD"), config("MYSQL_DB"))
            self.mysql_cursor = self.mysql_conn.cursor()
            print("[*] MySQL database connection established via .env")
        else:
            print("CRITICAL: .env file missing for MySQL credentials")
            exit(1)

    def _default_output_formatter(self, count, t1, t2, imsi_str, c_name, b_name, o_name, mcc, mnc, lac, cell, ts, pkt=None):
        t1 = str(t1 or "")
        t2 = str(t2 or "")
        imsi_str = str(imsi_str or "")
        c_name = str(c_name or "")
        b_name = str(b_name or "")
        o_name = str(o_name or "")
        print(f"{str(count):7s} | {t1:10s} | {t2:10s} | {imsi_str:17s} | {c_name:16s} | {b_name:14s} | {o_name:21s} | {str(mcc):4s} | {str(mnc):5s} | {str(lac):6s} | {str(cell):6s} | {ts.isoformat():s}", flush=True)

    def dispatch_observation(self, count, tmsi1, tmsi2, imsi, mcc, mnc, lac, cell, pkt=None):
        c_name = self.country
        b_name = self.brand
        o_name = self.operator

        if imsi:
            imsi, c_name, b_name, o_name = self.extract_imsi_metadata(imsi, pkt)
            
        current_time = datetime.datetime.now()
        self.output_handler(count, tmsi1, tmsi2, imsi, c_name, b_name, o_name, mcc, mnc, lac, cell, current_time, pkt)

        if self.txt_log_path:
            with open(self.txt_log_path, "a") as f_out:
                f_out.write(f"{str(current_time)}, {tmsi1}, {tmsi2}, {imsi}, {c_name}, {b_name}, {o_name}, {mcc}, {mnc}, {lac}, {cell}\n")

        if self.sqlite_conn:
            self.sqlite_conn.execute(
               "INSERT INTO observations (stamp, tmsi1, tmsi2, imsi, imsicountry, imsibrand, imsioperator, mcc, mnc, lac, cell) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);",
               (current_time, tmsi1 or None, tmsi2 or None, imsi, c_name, b_name, o_name, mcc, mnc, lac, cell)
            )
            self.sqlite_conn.commit()

        if self.mysql_cursor:
            query = "INSERT INTO `imsi` (`tmsi1`, `tmsi2`, `imsi`,`mcc`, `mnc`, `lac`, `cell_id`, `stamp`, `deviceid`) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)"
            self.mysql_cursor.execute(query, (tmsi1, tmsi2, imsi, mcc, mnc, lac, cell, current_time, "rtl"))
            self.mysql_conn.commit()

    def print_headers(self):
        print(f"{'Count':7s} | {'TMSI-1':10s} | {'TMSI-2':10s} | {'IMSI':17s} | {'Country':16s} | {'Brand':14s} | {'Operator':21s} | {'MCC':4s} | {'MNC':5s} | {'LAC':6s} | {'Cell':6s} | Timestamp")

    def process_identity(self, arfcn, imsi1="", imsi2="", tmsi1="", tmsi2="", packet_data=""):
        should_log = False
        seq_num = ''
        
        t1_hex = self._format_tmsi_hex(tmsi1)
        t2_hex = self._format_tmsi_hex(tmsi2)
        
        if imsi1: self._mark_seen(imsi1, arfcn)
        if imsi2: self._mark_seen(imsi2, arfcn)

        # Logic for parsing and matching target IMSI
        for idx, current_imsi in enumerate([imsi1, imsi2]):
            if not current_imsi: continue
            
            if not self.target_imsi or current_imsi[:self.target_imsi_len] == self.target_imsi:
                if current_imsi not in self.imsi_list:
                    should_log = True
                    self.imsi_list.append(current_imsi)
                    self.imsi_count += 1
                    seq_num = self.imsi_count
                    
                for t_hex in [t1_hex, t2_hex]:
                    if t_hex and (t_hex not in self.tmsi_map or self.tmsi_map[t_hex] != current_imsi):
                        should_log = True
                        self.tmsi_map[t_hex] = current_imsi

        if not imsi1 and not imsi2 and t1_hex and t2_hex:
            if t2_hex in self.tmsi_map:
                should_log = True
                imsi1 = self.tmsi_map[t2_hex]
                self.tmsi_map[t1_hex] = imsi1
                del self.tmsi_map[t2_hex]

        if should_log:
            if imsi1: self.dispatch_observation(str(seq_num), t1_hex, t2_hex, imsi1, str(self.mcc), str(self.mnc), str(self.lac), str(self.cell_id), packet_data)
            if imsi2: self.dispatch_observation(str(seq_num), t1_hex, t2_hex, imsi2, str(self.mcc), str(self.mnc), str(self.lac), str(self.cell_id), packet_data)

        if not imsi1 and not imsi2:
            if t1_hex and t1_hex in self.tmsi_map and self.tmsi_map[t1_hex] != "":
                self._mark_seen(self.tmsi_map[t1_hex], arfcn)
                
            if self.display_all_tmsi:
                should_log = False
                for t_hex in [t1_hex, t2_hex]:
                    if t_hex and t_hex not in self.tmsi_map:
                        should_log = True
                        self.tmsi_map[t_hex] = ""
                if should_log:
                    self.dispatch_observation(str(seq_num), t1_hex, t2_hex, None, str(self.mcc), str(self.mnc), str(self.lac), str(self.cell_id), packet_data)

    def _mark_seen(self, imsi_val, arfcn):
        ts = datetime.datetime.utcnow().replace(microsecond=0)
        imsi_decoded, _, _ = self._decode_raw_imsi(imsi_val)
        
        if imsi_decoded in self.active_imsis:
            self.active_imsis[imsi_decoded]["last_ts"] = ts
        else:
            self.active_imsis[imsi_decoded] = {
                "first_ts": ts,
                "last_ts": ts,
                "imsi": imsi_decoded,
                "arfcn": arfcn,
            }
        self._prune_stale_records()

    def _prune_stale_records(self):
        curr_time = datetime.datetime.utcnow().replace(microsecond=0)
        threshold = curr_time - datetime.timedelta(minutes=self.purge_timeout_mins)
        stale_keys = [k for k, v in self.active_imsis.items() if v["last_ts"] < threshold]
        for k in stale_keys:
            del self.active_imsis[k]


class GSMTapHeader(ctypes.BigEndianStructure):
    _pack_ = 1
    _fields_ = [
        ("version", ctypes.c_ubyte), ("hdr_len", ctypes.c_ubyte), ("type", ctypes.c_ubyte),
        ("timeslot", ctypes.c_ubyte), ("arfcn", ctypes.c_uint16), ("signal_dbm", ctypes.c_ubyte),
        ("snr_db", ctypes.c_ubyte), ("frame_num", ctypes.c_uint32), ("sub_type", ctypes.c_ubyte),
        ("antenna_id", ctypes.c_ubyte), ("sub_slot", ctypes.c_ubyte), ("reserved", ctypes.c_ubyte),
    ]

def parse_cell_identity_packet(gsm_hdr, payload, monitor_inst=None):
    if gsm_hdr.sub_type == 0x01: # BCCH Channel
        b_array = bytearray(payload)
        if b_array[0x12] == 0x1b: # System Information Type 3
            mcc_hex = hex(b_array[0x15])
            mcc_val = (mcc_hex[2] + '0' if len(mcc_hex) < 4 else mcc_hex[3] + mcc_hex[2]) + str(b_array[0x16] & 0x0f)
            
            mnc_hex = hex(b_array[0x17])
            mnc_val = mnc_hex[2] + '0' if len(mnc_hex) < 4 else mnc_hex[3] + mnc_hex[2]
            
            loc_area_code = b_array[0x18] * 256 + b_array[0x19]
            cell_identifier = b_array[0x13] * 256 + b_array[0x14]
            monitor_inst.update_cell_info(mcc_val, mnc_val, loc_area_code, cell_identifier)

def extract_imsi_payload(udp_payload, monitor_inst=None):
    if not monitor_inst:
        monitor_inst = global_tracker

    hdr = GSMTapHeader.from_buffer_copy(udp_payload)

    if hdr.sub_type == 0x1:
        parse_cell_identity_packet(hdr, udp_payload, monitor_inst)
    else:
        b_array = bytearray(udp_payload)
        t_id1, t_id2, i_id1, i_id2 = "", "", "", ""
        
        msg_type = b_array[0x12]
        if msg_type == 0x21: # Paging Request Type 1
            if b_array[0x14] == 0x08 and (b_array[0x15] & 0x1) == 0x1:
                i_id1 = b_array[0x15:0x15+8]
                if b_array[0x10] == 0x59 and b_array[0x1E] == 0x08 and (b_array[0x1F] & 0x1) == 0x1:
                    i_id2 = b_array[0x1F:0x1F+8]
                elif b_array[0x10] == 0x4d and b_array[0x1E] == 0x05 and b_array[0x1F] == 0xf4:
                    t_id1 = b_array[0x20:0x20+4]
                monitor_inst.process_identity(hdr.arfcn, i_id1, i_id2, t_id1, t_id2, b_array)

            elif b_array[0x1B] == 0x08 and (b_array[0x1C] & 0x1) == 0x1:
                t_id1 = b_array[0x16:0x16+4]
                i_id2 = b_array[0x1C:0x1C+8]
                monitor_inst.process_identity(hdr.arfcn, i_id1, i_id2, t_id1, t_id2, b_array)

            elif b_array[0x14] == 0x05 and (b_array[0x15] & 0x07) == 4:
                t_id1 = b_array[0x16:0x16+4]
                if b_array[0x1B] == 0x05 and (b_array[0x1C] & 0x07) == 4:
                    t_id2 = b_array[0x1D:0x1D+4]
                monitor_inst.process_identity(hdr.arfcn, i_id1, i_id2, t_id1, t_id2, b_array)

        elif msg_type == 0x22: # Paging Request Type 2
            if b_array[0x1D] == 0x08 and (b_array[0x1E] & 0x1) == 0x1:
                t_id1 = b_array[0x14:0x14+4]
                t_id2 = b_array[0x18:0x18+4]
                i_id2 = b_array[0x1E:0x1E+8]
                monitor_inst.process_identity(hdr.arfcn, i_id1, i_id2, t_id1, t_id2, b_array)

def launch_udp_listener(port_num, callback_ptr):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    # Increase socket buffer to 4MB to prevent 'OOOO' overruns on high-speed streams
    s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4194304)
    s.bind(('localhost', port_num))
    print(f"[*] Native UDP Listener bound to port {port_num}")
    while True:
        data, _ = s.recvfrom(4096)
        if callback_ptr: callback_ptr(data)

def _scapy_callback_wrapper(packet):
    pass

if __name__ == "__main__":
    global_tracker = ImsiMonitor()
    
    cli = OptionParser()
    cli.add_option("-a", "--alltmsi", action="store_true", dest="display_all", help="Log un-correlated TMSIs")
    cli.add_option("-i", "--iface", dest="net_iface", default="lo", help="Sniffer interface")
    cli.add_option("-m", "--imsi", dest="target_imsi", default="", type="string", help="Specific IMSI prefix to look for")
    cli.add_option("-p", "--port", dest="listen_port", default=4733, type="int", help="Base UDP listening port")
    cli.add_option("-s", "--sniff", action="store_true", dest="use_scapy", help="Use Scapy sniffing on IFACE instead of binding a native socket")
    cli.add_option("-w", "--sqlite", dest="db_sqlite", default=None, type="string", help="Path to SQLite output database")
    cli.add_option("-t", "--txt", dest="log_txt", default=None, type="string", help="Path to Plaintext output file")
    cli.add_option("-z", "--mysql", action="store_true", dest="db_mysql", help="Log into a MySQL database configured in .env")
    
    (cfg, _) = cli.parse_args()

    if cfg.db_sqlite:
        global_tracker.setup_sqlite(cfg.db_sqlite)
    if cfg.log_txt:
        global_tracker.setup_txt_log(cfg.log_txt)
    if cfg.db_mysql:
        global_tracker.setup_mysql()

    global_tracker.display_all_tmsi = cfg.display_all

    if cfg.target_imsi:
        sanitized_imsi = "9" + cfg.target_imsi.replace(" ", "")
        length = len(sanitized_imsi)
        if length % 2 == 0 and 0 < length < 17:
            packed = ""
            for i in range(0, length - 1, 2):
                packed += chr(int(sanitized_imsi[i + 1]) * 16 + int(sanitized_imsi[i]))
            global_tracker.filter_imsi(packed)
        else:
            print("CRITICAL: Invalid IMSI Target Length.")
            exit(1)

    global_tracker.print_headers()

    if cfg.use_scapy:
        print("Scapy engine is disabled for performance. Use default native listener.")
    else:
        launch_udp_listener(cfg.listen_port, extract_imsi_payload)
