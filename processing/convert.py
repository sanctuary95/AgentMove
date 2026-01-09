import os
import csv
import pandas as pd
import os
# # 让脚本无论从哪里运行，都以 repo 根目录为基准
# REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))



# src_txt = os.path.join(REPO_ROOT, "data/nominatim/New York_address.txt")
# dst_csv = os.path.join(REPO_ROOT, "data/nominatim/New York.csv")

# df = pd.read_csv(
#     src_txt,
#     sep="\t",
#     header=None,
#     names=["city", "place_id", "lon", "lat", "address"],
#     encoding="utf-8"
# )

# df.to_csv(dst_csv, index=False)


import csv
import re
input_txt = "/data/zke4/Sy/MOVEMAS/Baseline/AgentMove/data/nominatim/New York_address.txt"
output_csv = "/data/zke4/Sy/MOVEMAS/Baseline/AgentMove/data/nominatim/New York10.csv"


# input_txt = "input.txt"
# output_csv = "output.csv"

# 解析规则：
# 1) city：行首，直到遇到 venue_id
# 2) venue_id：24位十六进制
# 3) lon/lat：浮点数（含负号）
# 4) address：剩余全部
pattern = re.compile(
    r"^\s*(?P<city>.+?)\s+"
    r"(?P<venue_id>[0-9a-f]{24})\s+"
    r"(?P<lon>-?\d+(?:\.\d+)?)\s+"
    r"(?P<lat>-?\d+(?:\.\d+)?)\s+"
    r"(?P<address>.+?)\s*$",
    re.IGNORECASE
)

bad_lines = 0
total_lines = 0

with open(input_txt, "r", encoding="utf-8") as fin, \
     open(output_csv, "w", newline="", encoding="utf-8") as fout:

    writer = csv.writer(
        fout,
        delimiter=",",
        quotechar='"',
        quoting=csv.QUOTE_MINIMAL
    )
    writer.writerow(["city", "venue_id", "lon", "lat", "address"])

    for line in fin:
        total_lines += 1
        line = line.strip()
        if not line:
            continue

        m = pattern.match(line)
        if not m:
            bad_lines += 1
            continue

        city = m.group("city").strip()
        venue_id = m.group("venue_id").strip()
        lon = m.group("lon").strip()
        lat = m.group("lat").strip()
        address = m.group("address").strip()

        writer.writerow([city, venue_id, lon, lat, address])

print(f"Done. total_lines={total_lines}, bad_lines={bad_lines}, output={output_csv}")

# with open(input_txt, "r", encoding="utf-8") as fin, \
#      open(output_csv, "w", newline="", encoding="utf-8") as fout:

#     writer = csv.writer(
#         fout,
#         delimiter=",",
#         quotechar='"',
#         quoting=csv.QUOTE_MINIMAL
#     )

#     # 写表头
#     writer.writerow(["city", "venue_id", "lon", "lat", "address"])

#     for line in fin:
#         line = line.strip()
#         if not line:
#             continue

#         # 按任意空白符切分（多个空格 / tab 都可以）
#         parts = line.split()

#         if len(parts) < 5:
#             continue  # 异常行，直接跳过

#         city = parts[0]
#         venue_id = parts[1]
#         lon = parts[2]
#         lat = parts[3]

#         # 剩余部分全部拼成 address
#         address = " ".join(parts[4:])

#         writer.writerow([city, venue_id, lon, lat, address])
