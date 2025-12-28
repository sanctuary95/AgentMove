# convert_osm_web_txt_to_tsv.py
import os
import csv

src_txt = "data/nominatim/New York_address.txt"
dst_tsv = "data/nominatim/New York.csv"   # trajectory_address_match.py 会用 sep="\t" 读它

os.makedirs(os.path.dirname(dst_tsv), exist_ok=True)

total = 0
kept = 0
bad = 0

with open(src_txt, "r", encoding="utf-8", errors="replace") as fin, \
     open(dst_tsv, "w", encoding="utf-8", newline="") as fout:

    # 写表头：至少要有 venue_id 和 address
    writer = csv.writer(fout, delimiter="\t")
    writer.writerow(["venue_id", "address", "lon", "lat", "city"])

    for line in fin:
        total += 1
        line = line.rstrip("\n")
        if not line.strip():
            continue

        parts = line.split("\t")

        # 允许 address 中包含 tab：把多余部分拼回 address
        # 情况1：city, venue_id, lon, lat, address...
        if len(parts) >= 5:
            city = parts[0].strip()
            venue_id = parts[1].strip()
            lon = parts[2].strip()
            lat = parts[3].strip()
            address = "\t".join(parts[4:]).strip()
        # 情况2：venue_id, lon, lat, address...
        elif len(parts) == 4:
            city = ""
            venue_id = parts[0].strip()
            lon = parts[1].strip()
            lat = parts[2].strip()
            address = parts[3].strip()
        else:
            bad += 1
            continue

        if not venue_id or not address:
            bad += 1
            continue

        writer.writerow([venue_id, address, lon, lat, city])
        kept += 1

print("Converted.")
print("src:", src_txt)
print("dst:", dst_tsv)
print("total lines:", total)
print("kept rows:", kept)
print("bad/skipped:", bad)