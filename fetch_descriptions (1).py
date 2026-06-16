import pandas as pd
import numpy as np
import requests
import time
import os
import json

# ── 1. Load & lọc sơ bộ ────────────────────────────────────────────────────

df = pd.read_csv("Books__2_.csv", low_memory=False)
df["Year-Of-Publication"] = pd.to_numeric(df["Year-Of-Publication"], errors="coerce")

df = df[
    ~df["ISBN"].astype(str).str.startswith("B") &    # bỏ Amazon ASIN
    (df["ISBN"].astype(str).str.len() == 10) &        # chỉ ISBN-10 đúng độ dài
    df["Book-Title"].notna() &
    df["Book-Author"].notna() &
    df["Year-Of-Publication"].between(1800, 2024)
].reset_index(drop=True)

print(f"Sách đưa vào xử lý: {len(df):,}")


# ── 2. Chuyển ISBN-10 → ISBN-13 ────────────────────────────────────────────

def isbn10_to_isbn13(isbn10: str) -> str:
    isbn10 = str(isbn10).strip()
    base = "978" + isbn10[:-1]
    total = sum(int(d) * (1 if i % 2 == 0 else 3) for i, d in enumerate(base))
    check = (10 - (total % 10)) % 10
    return base + str(check)

df["ISBN13"] = df["ISBN"].apply(isbn10_to_isbn13)


# ── 3. Hàm gọi API ─────────────────────────────────────────────────────────

def fetch_google_books(isbn13: str) -> str | None:
    """Trả về description hoặc None nếu không tìm thấy."""
    try:
        url = f"https://www.googleapis.com/books/v1/volumes?q=isbn:{isbn13}"
        resp = requests.get(url, timeout=5)
        data = resp.json()
        items = data.get("items", [])
        if not items:
            return None
        desc = items[0].get("volumeInfo", {}).get("description", "")
        return desc.strip() if desc and len(desc) > 50 else None
    except Exception:
        return None


def fetch_open_library(isbn13: str) -> str | None:
    """Fallback: Open Library API."""
    try:
        url = f"https://openlibrary.org/api/books?bibkeys=ISBN:{isbn13}&format=json&jscmd=data"
        resp = requests.get(url, timeout=5)
        data = resp.json()
        key = f"ISBN:{isbn13}"
        if key not in data:
            return None
        desc = data[key].get("description", "")
        if isinstance(desc, dict):
            desc = desc.get("value", "")
        return desc.strip() if desc and len(desc) > 50 else None
    except Exception:
        return None


# ── 4. Vòng lặp chính với checkpoint ───────────────────────────────────────

CHECKPOINT_FILE = "checkpoint.json"
OUTPUT_FILE = "books_with_descriptions.csv"
BATCH_SIZE = 100      # lưu checkpoint mỗi 100 cuốn
DELAY = 0.5           # giây giữa mỗi request (tránh rate limit)

# Load checkpoint nếu đã chạy dở
if os.path.exists(CHECKPOINT_FILE):
    with open(CHECKPOINT_FILE) as f:
        checkpoint = json.load(f)
    start_idx = checkpoint["last_index"] + 1
    results = checkpoint["results"]
    print(f"Tiếp tục từ index {start_idx}")
else:
    start_idx = 0
    results = []

# Vòng lặp fetch
for i in range(start_idx, len(df)):
    row = df.iloc[i]
    isbn13 = row["ISBN13"]

    # Thử Google Books trước
    description = fetch_google_books(isbn13)

    # Fallback sang Open Library nếu Google Books không có
    if not description:
        description = fetch_open_library(isbn13)

    # Chỉ giữ sách lấy được description
    if description:
        results.append({
            "ISBN":                  row["ISBN"],
            "ISBN13":                isbn13,
            "Book-Title":            row["Book-Title"],
            "Book-Author":           row["Book-Author"],
            "Year-Of-Publication":   row["Year-Of-Publication"],
            "Publisher":             row["Publisher"],
            "Image-URL-L":           row["Image-URL-L"],
            "description":           description,
        })

    # In tiến độ mỗi 500 cuốn
    if (i + 1) % 500 == 0:
        hit_rate = len(results) / (i + 1) * 100
        print(f"[{i+1:>6}/{len(df)}]  Lấy được: {len(results):,}  ({hit_rate:.1f}%)")

    # Lưu checkpoint mỗi BATCH_SIZE cuốn
    if (i + 1) % BATCH_SIZE == 0:
        with open(CHECKPOINT_FILE, "w") as f:
            json.dump({"last_index": i, "results": results}, f)
        pd.DataFrame(results).to_csv(OUTPUT_FILE, index=False)

    time.sleep(DELAY)

# Lưu kết quả cuối
pd.DataFrame(results).to_csv(OUTPUT_FILE, index=False)
if os.path.exists(CHECKPOINT_FILE):
    os.remove(CHECKPOINT_FILE)

print(f"\nHoàn thành!")
print(f"Tổng đầu vào:       {len(df):,} cuốn")
print(f"Lấy được description: {len(results):,} cuốn ({len(results)/len(df)*100:.1f}%)")
print(f"Đã lưu ra: {OUTPUT_FILE}")
