#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Description:
# Fetches the latest MCC/MNC mappings directly from Wikipedia
# and exports them as a JSON dictionary for live lookup.

import json
import io
import sys

try:
    from bs4 import BeautifulSoup
except ImportError:
    print("CRITICAL: BeautifulSoup4 is required. Try `pip install bs4`")
    sys.exit(1)

try:
    from urllib.request import urlopen
    is_py3 = True
except ImportError:
    from urllib2 import urlopen
    is_py3 = False

TARGET_URLS = [
    'https://en.wikipedia.org/wiki/Mobile_Network_Codes_in_ITU_region_2xx_(Europe)',
    'https://en.wikipedia.org/wiki/Mobile_Network_Codes_in_ITU_region_3xx_(North_America)',
    'https://en.wikipedia.org/wiki/Mobile_Network_Codes_in_ITU_region_4xx_(Asia)',
    'https://en.wikipedia.org/wiki/Mobile_Network_Codes_in_ITU_region_5xx_(Oceania)',
    'https://en.wikipedia.org/wiki/Mobile_Network_Codes_in_ITU_region_6xx_(Africa)',
    'https://en.wikipedia.org/wiki/Mobile_Network_Codes_in_ITU_region_7xx_(South_America)'
]

def scrape_mcc_data():
    network_map = {}
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html'
    }
    
    for page_url in TARGET_URLS:
        try:
            if is_py3:
                import urllib.request
                req = urllib.request.Request(page_url, headers=headers)
                html_doc = urlopen(req)
            else:
                import urllib2
                req = urllib2.Request(page_url, headers=headers)
                html_doc = urlopen(req)
            parser = BeautifulSoup(html_doc, 'html.parser')
            
            for table in parser.find_all("table", class_="wikitable"):
                if 'MCC' not in table.text:
                    continue
                
                h_node = table.find_previous_sibling("div", class_=lambda c: c and "mw-heading" in c)
                if not h_node:
                    h_node = table.find_previous_sibling("h4")
                if not h_node:
                    continue
                
                header_text = h_node.text.replace('[edit]', '').replace('edit', '').strip()
                if ' - ' in header_text:
                    header_parts = header_text.split(' - ')
                elif ' \u2013 ' in header_text:
                    header_parts = header_text.split(' \u2013 ')
                elif ' – ' in header_text:
                    header_parts = header_text.split(' – ')
                else:
                    continue
                    
                country_name = header_parts[0].strip()
                country_iso = header_parts[1].strip()
                
                for row in table.find_all('tr'):
                    cells = row.find_all('td')
                    if len(cells) < 4:
                        continue
                        
                    mcc_val = cells[0].text.strip()
                    if not mcc_val:
                        continue
                        
                    mnc_val = cells[1].text.strip()
                    brand_val = cells[2].text.strip()
                    operator_val = cells[3].text.strip()
                    
                    if mcc_val not in network_map:
                        network_map[mcc_val] = {}
                        
                    network_map[mcc_val][mnc_val] = [brand_val, operator_val, country_name, country_iso]
        except Exception as e:
            print(f"Warning: Failed to parse a table in {page_url} - {str(e)}")
            
    return network_map

if __name__ == '__main__':
    print("[*] Updating MCC/MNC mappings...")
    extracted_data = scrape_mcc_data()
    
    import os
    if extracted_data:
        file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'mcc_codes.json')
        with io.open(file_path, 'w', encoding='utf8') as f:
            if is_py3:
                f.write(json.dumps(extracted_data, ensure_ascii=False, indent=2))
            else:
                f.write(json.dumps(extracted_data, ensure_ascii=False, encoding="utf-8", indent=2))
        print(f"[*] Success! Saved {len(extracted_data)} MCC regions to {file_path}")
    else:
        print("[!] Failed to extract any region data.")
