#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Description:
# Parses raw GSM packets to extract SDCCH, Subchannel, Timeslot, 
# Hopping Channel status, and ARFCN from Immediate Assignment messages.

from scapy.all import sniff
from optparse import OptionParser

def parse_immediate_assignment(pkt):
    """
    Decodes the immediate assignment from the GSMTAP header.
    Expects GSMTAP + CCCH + RR Immediate Assignment parameters.
    """
    raw_bytes = bytes(pkt)
    
    if len(raw_bytes) < 0x41:
        return # Packet too small to be valid

    # Offset 0x36 corresponds to the GSMTAP Channel Type block.
    # 0x01 == BCCH / non-BCCH filter. Actually checking if it's NOT BCCH.
    if raw_bytes[0x36] != 0x01:
        # 0x3C is the Message Type, 0x3F indicates Immediate Assignment
        if raw_bytes[0x3C] == 0x3F:
            assignment_type = raw_bytes[0x3D] >> 4
            
            # 0 = Dedicated mode or TBF (Dedicated mode resource assignment)
            if assignment_type == 0:
                sdcch_val = raw_bytes[0x3E] >> 3
                subchannel_val = raw_bytes[0x3E]
                timeslot_val = raw_bytes[0x3E] & 0x07
                is_hopping = "yes" if ((raw_bytes[0x3F] >> 4) & 1) == 1 else "no"
                arfcn_val = (raw_bytes[0x3F] & 0x03) * 256 + raw_bytes[0x40]
                
                print(f"{sdcch_val}\t; {subchannel_val}\t\t; {timeslot_val}\t\t; {is_hopping}\t\t\t; {arfcn_val}")
            else:
                # 1 = Downlink/Uplink TBF
                sdcch_val = "-"
                subchannel_val = "-"
                timeslot_val = raw_bytes[0x3E] & 0x07
                is_hopping = "-"
                arfcn_val = (raw_bytes[0x3F] & 0x03) * 256 + raw_bytes[0x40]
                
                print(f"{sdcch_val}\t; {subchannel_val}\t\t; {timeslot_val}\t\t; {is_hopping}\t\t\t; {arfcn_val}")

if __name__ == "__main__":
    cli_parser = OptionParser(usage="%prog: [options]")
    cli_parser.add_option("-i", "--iface", dest="interface", default="lo", help="Network Interface (default : lo)")
    cli_parser.add_option("-p", "--port", dest="target_port", default="4729", type="int", help="Target UDP port (default : 4729)")
    
    (opts, _) = cli_parser.parse_args()
    
    print("SDCCH\t; Subchannel\t; Timeslot\t; HoppingChannel\t; ARFCN")
    bpf_filter = f"port {opts.target_port} and udp and not icmp"
    
    sniff(iface=opts.interface, filter=bpf_filter, prn=parse_immediate_assignment, store=0)