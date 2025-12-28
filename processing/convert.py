import os
import csv
import pandas as pd
import os
# 让脚本无论从哪里运行，都以 repo 根目录为基准
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))



src_txt = os.path.join(REPO_ROOT, "data/nominatim/New York_address2.txt")
dst_csv = os.path.join(REPO_ROOT, "data/nominatim/New York.csv")

df = pd.read_csv(
    src_txt,
    sep="\t",
    header=None,
    names=["city", "place_id", "lon", "lat", "address"],
    encoding="utf-8"
)

df.to_csv(dst_csv, index=False)
