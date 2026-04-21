# MongoDB → Notion Sync via GitHub Actions

A guide to automatically syncing new MongoDB records to a Notion database using GitHub Actions cron jobs — no server required.

---

## Project Structure

```
your-repo/
├── sync_script.py          ← your sync logic
├── requirements.txt        ← Python dependencies
└── .github/
    └── workflows/
        └── sync.yml        ← GitHub Actions cron workflow
```

---

## Step 1: Set Up Your Repository

Create a new GitHub repository (public or private) and push the following files.

---

## Step 2: `requirements.txt`

```
pymongo
notion-client
dnspython
```

> `dnspython` is required for MongoDB Atlas SRV-format connection strings.

---

## Step 3: `sync_script.py`

Update your script to read credentials from environment variables instead of hardcoding them:

```python
import os
import re
from datetime import date, datetime
from pymongo import MongoClient
from notion_client import Client

# ── Credentials from environment (set as GitHub Secrets) ──────────────────────
MONGO_URI    = os.environ["MONGO_URI"]
NOTION_TOKEN = os.environ["NOTION_TOKEN"]
NOTION_DB_ID = os.environ["NOTION_DB_ID"]

DB_NAME    = "v6"
COLLECTION = "OC-WI-14.01 Culture Transfer"

# ── Clients ────────────────────────────────────────────────────────────────────
mongo_client = MongoClient(MONGO_URI)
notion       = Client(auth=NOTION_TOKEN)


# ── Date parsers ───────────────────────────────────────────────────────────────
def parse_source_inoculation(value):
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value.isoformat()
    value_str = str(value).strip()
    match = re.search(r"(\d{6})", value_str)
    if match:
        value_str = match.group(1)
    try:
        return datetime.strptime(value_str, "%y%m%d").date().isoformat()
    except ValueError:
        return None


def parse_date_inoculation(value):
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value.isoformat()
    value_str = str(value).strip()
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m-%d-%Y"):
        try:
            return datetime.strptime(value_str, fmt).date().isoformat()
        except ValueError:
            continue
    return None


# ── Main sync ──────────────────────────────────────────────────────────────────
def main():
    # Only fetch documents not yet synced to Notion
    docs = list(mongo_client[DB_NAME][COLLECTION].find(
        {"syncedToNotion": {"$ne": True}},
        {
            "SourceBatchNum": 1, "BatchNum": 1,
            "SourceVesselSize": 1, "NewVesselSize": 1,
            "SourceInoculation": 1, "DateInoculation": 1,
        }
    ))

    synced_count  = 0
    skipped_count = 0

    for doc in docs:
        source_inoculation = parse_source_inoculation(doc.get("SourceInoculation"))
        date_inoculation   = parse_date_inoculation(doc.get("DateInoculation"))

        if not source_inoculation or not date_inoculation:
            skipped_count += 1
            print(f"⚠️  Skipping {doc.get('BatchNum', '<unknown>')} — date parsing failed")
            continue

        notion.pages.create(
            parent={"database_id": NOTION_DB_ID},
            properties={
                "SourceBatchNum":  {"title":     [{"text": {"content": str(doc.get("SourceBatchNum", ""))}}]},
                "BatchNum":        {"rich_text": [{"text": {"content": str(doc.get("BatchNum", ""))}}]},
                "SourceVesselSize":{"number":    float(doc.get("SourceVesselSize") or 0)},
                "NewVesselSize":   {"number":    float(doc.get("NewVesselSize") or 0)},
                "Start Date":      {"date":      {"start": source_inoculation}},
                "End Date":        {"date":      {"start": date_inoculation}},
            }
        )

        # Mark as synced in MongoDB so it's never duplicated
        mongo_client[DB_NAME][COLLECTION].update_one(
            {"_id": doc["_id"]},
            {"$set": {"syncedToNotion": True}}
        )
        synced_count += 1

    print(f"✅ Synced: {synced_count}  |  ⚠️ Skipped: {skipped_count}")
    mongo_client.close()


if __name__ == "__main__":
    main()
```

### Key change: `syncedToNotion` flag

After each successful Notion page creation, the script marks the MongoDB document with `syncedToNotion: true`. On the next run, those records are excluded from the query — so **no duplicates are ever created**, regardless of how many times the cron fires.

---

## Step 4: `.github/workflows/sync.yml`

```yaml
name: Sync MongoDB to Notion

on:
  schedule:
    - cron: '*/30 * * * *'   # every 30 minutes (UTC)
  workflow_dispatch:           # allows manual trigger from GitHub UI

jobs:
  sync:
    runs-on: ubuntu-latest

    steps:
      - name: Checkout repo
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt

      - name: Run sync script
        env:
          MONGO_URI:    ${{ secrets.MONGO_URI }}
          NOTION_TOKEN: ${{ secrets.NOTION_TOKEN }}
          NOTION_DB_ID: ${{ secrets.NOTION_DB_ID }}
        run: python sync_script.py
```

> **Why `*/30` and not `*/15`?** See the free-tier math below.

---

## Step 5: Add GitHub Secrets

Secrets are encrypted environment variables injected into the workflow at runtime. They are **never visible in logs**.

1. Go to your GitHub repo
2. Click **Settings** → **Secrets and variables** → **Actions**
3. Click **New repository secret** and add all three:

| Secret Name    | Value                                   |
|----------------|-----------------------------------------|
| `MONGO_URI`    | Your full MongoDB Atlas connection string |
| `NOTION_TOKEN` | Your Notion integration token           |
| `NOTION_DB_ID` | Your Notion database ID                 |

---

## Free Tier Usage Math

GitHub Actions gives **2,000 minutes/month** free for private repos (unlimited for public repos).

### At `*/15` (every 15 minutes)

| | Calculation | Result |
|---|---|---|
| Runs/hour | 60 ÷ 15 | 4 |
| Runs/day | 4 × 24 | 96 |
| Runs/month | 96 × 30 | 2,880 |
| Minutes @ 30s/run | 2,880 × 0.5 | **1,440 min** ✅ |
| Minutes @ 60s/run | 2,880 × 1.0 | **2,880 min** ❌ |

### At `*/30` (every 30 minutes) — Recommended

| | Calculation | Result |
|---|---|---|
| Runs/hour | 60 ÷ 30 | 2 |
| Runs/day | 2 × 24 | 48 |
| Runs/month | 48 × 30 | 1,440 |
| Minutes @ 60s/run | 1,440 × 1.0 | **1,440 min** ✅ |

**Conclusion:** `*/30` keeps you safely under 2,000 min/month even in the worst case.

---

## Important Limitations

| Limitation | Detail |
|---|---|
| Minimum interval | 5 minutes (`*/5 * * * *`) — can't go lower |
| Timezone | All cron times are **UTC**, not IST (IST = UTC+5:30) |
| Delay | Runs can be delayed up to **30 minutes** during GitHub peak load |
| Inactivity disable | Scheduled workflows are **auto-disabled after 60 days** of repo inactivity — push a commit or manually trigger to keep alive |

---

## How to Manually Trigger

1. Go to your repo on GitHub
2. Click the **Actions** tab
3. Select **Sync MongoDB to Notion** from the left sidebar
4. Click **Run workflow** → **Run workflow**

This is useful for testing before the first scheduled run fires.

---

## Monitoring Runs

After the workflow runs, you can inspect every log:

1. **Actions tab** → click a run → click the `sync` job
2. You'll see each step's output, including your `print()` statements
3. A green checkmark = success; red X = failure (GitHub will email you on failure)

---

## Summary Flow

```
Every 30 min (UTC)
       │
       ▼
GitHub Actions runner spins up
       │
       ▼
Queries MongoDB for { syncedToNotion: { $ne: true } }
       │
       ▼
For each new doc → creates Notion page
       │
       ▼
Sets syncedToNotion: true in MongoDB
       │
       ▼
Runner shuts down (~30–60 seconds total)
```
