#!/usr/bin/env python3
"""One-shot script: load all CSV files and push them into MongoDB Atlas.

Run once locally:
    python migrate_csv_to_mongo.py

After confirming the data is in Mongo you can delete this script.
"""

import os, sys
import pandas as pd
from pymongo import MongoClient

# ── Read connection info from .streamlit/secrets.toml manually ──────────────
import configparser, io

SECRETS_PATH = os.path.join(os.path.dirname(__file__), ".streamlit", "secrets.toml")
with open(SECRETS_PATH, "r") as f:
    raw = f.read()

# Quick TOML parse via configparser (good enough for simple secrets.toml)
cfg = configparser.ConfigParser()
cfg.read_string(raw)

MONGO_URI = cfg["mongo"]["uri"].strip('"').strip("'")
MONGO_DB  = cfg["mongo"]["db"].strip('"').strip("'")

client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
client.admin.command("ping")
print(f"✅ Connected to MongoDB Atlas — database: {MONGO_DB}")
db = client[MONGO_DB]

BASE = os.path.dirname(__file__)

# Mapping: (csv filename, collection name, expected columns)
FILES = [
    ("recipes.csv",            "recipes",            None),
    ("meal_history.csv",       "meal_history",        None),
    ("pantry_staples.csv",     "pantry_staples",      None),
    ("ingredient_pricing.csv", "ingredient_pricing",  None),
    ("price_history.csv",      "price_history",       None),
]

total = 0
for csv_name, col_name, _ in FILES:
    path = os.path.join(BASE, csv_name)
    if not os.path.exists(path):
        print(f"⏩ {csv_name} not found — skipping")
        continue

    df = pd.read_csv(path)
    if df.empty:
        print(f"⏩ {csv_name} is empty — skipping")
        continue

    # Replace NaN with empty string / 0 depending on dtype
    for c in df.columns:
        if df[c].dtype == "object":
            df[c] = df[c].fillna("")
        else:
            df[c] = df[c].fillna(0)

    records = df.to_dict("records")
    col = db[col_name]
    col.delete_many({})       # clear old data (idempotent re-run)
    col.insert_many(records)
    total += len(records)
    print(f"✅ {csv_name} → {col_name}: {len(records)} documents")

print(f"\n🎉 Migration complete — {total} total documents inserted.")
