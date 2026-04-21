import os
import re
from datetime import date, datetime

from notion_client import Client
from notion_client.errors import APIResponseError
from pymongo import MongoClient

# Connection settings from environment
MONGO_URI = os.environ["MONGO_URI"]
NOTION_TOKEN = os.environ["NOTION_TOKEN"]
NOTION_DB_ID = os.environ["NOTION_DB_ID"]
DB_NAME = os.environ.get("DB_NAME", "v6")
COLLECTION = os.environ.get("COLLECTION", "OC-WI-14.01 Culture Transfer")

REQUIRED_NOTION_PROPERTIES = {
    "SourceBatchNum": "title",
    "BatchNum": "rich_text",
    "SourceVesselSize": "number",
    "NewVesselSize": "number",
    "Start Date": "date",
    "End Date": "date",
}

# Clients
mongo_client = MongoClient(MONGO_URI)
notion = Client(auth=NOTION_TOKEN)


def normalize_notion_database_id(value):
    """Accept a raw Notion database id or a full Notion URL and return the id."""
    value_str = str(value).strip()

    # Match plain 32-char ID or hyphenated UUID-like ID.
    direct_match = re.search(r"([0-9a-fA-F]{32}|[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})", value_str)
    if direct_match:
        raw = direct_match.group(1).replace("-", "")
        return f"{raw[0:8]}-{raw[8:12]}-{raw[12:16]}-{raw[16:20]}-{raw[20:32]}"

    raise RuntimeError("NOTION_DB_ID is not a valid Notion database id or URL")


# Date parsers
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


def validate_notion_schema():
    database_id = normalize_notion_database_id(NOTION_DB_ID)

    try:
        db = notion.databases.retrieve(database_id=database_id)
    except APIResponseError as exc:
        raise RuntimeError(
            "Could not access Notion database. Verify NOTION_DB_ID is correct and share the database with integration 'Symbrosia_Sync'."
        ) from exc

    notion_properties = db.get("properties", {})

    missing = []
    wrong_type = []
    for prop_name, expected_type in REQUIRED_NOTION_PROPERTIES.items():
        prop = notion_properties.get(prop_name)
        if not prop:
            missing.append(prop_name)
            continue
        actual_type = prop.get("type")
        if actual_type != expected_type:
            wrong_type.append(f"{prop_name} (expected {expected_type}, got {actual_type})")

    if missing or wrong_type:
        details = []
        if missing:
            details.append(f"missing: {', '.join(missing)}")
        if wrong_type:
            details.append(f"type mismatches: {', '.join(wrong_type)}")
        raise RuntimeError("Notion database schema validation failed - " + " | ".join(details))

    print("Notion schema validation passed")


# Main sync
def main():
    validate_notion_schema()

    # Only fetch documents not yet synced to Notion
    docs = list(
        mongo_client[DB_NAME][COLLECTION].find(
            {"syncedToNotion": {"$ne": True}},
            {
                "SourceBatchNum": 1,
                "BatchNum": 1,
                "SourceVesselSize": 1,
                "NewVesselSize": 1,
                "SourceInoculation": 1,
                "DateInoculation": 1,
            },
        )
    )

    synced_count = 0
    skipped_count = 0
    synced_doc_ids = []

    for doc in docs:
        source_inoculation = parse_source_inoculation(doc.get("SourceInoculation"))
        date_inoculation = parse_date_inoculation(doc.get("DateInoculation"))

        if not source_inoculation or not date_inoculation:
            skipped_count += 1
            print(f"Skipping {doc.get('BatchNum', '<unknown>')} - date parsing failed")
            continue

        notion.pages.create(
            parent={"database_id": NOTION_DB_ID},
            properties={
                "SourceBatchNum": {"title": [{"text": {"content": str(doc.get("SourceBatchNum", ""))}}]},
                "BatchNum": {"rich_text": [{"text": {"content": str(doc.get("BatchNum", ""))}}]},
                "SourceVesselSize": {"number": float(doc.get("SourceVesselSize") or 0)},
                "NewVesselSize": {"number": float(doc.get("NewVesselSize") or 0)},
                "Start Date": {"date": {"start": source_inoculation}},
                "End Date": {"date": {"start": date_inoculation}},
            },
        )

        # Mark as synced in MongoDB so it's never duplicated
        update_result = mongo_client[DB_NAME][COLLECTION].update_one(
            {"_id": doc["_id"]},
            {"$set": {"syncedToNotion": True}},
        )
        if update_result.matched_count != 1:
            raise RuntimeError(f"Failed to mark document as synced: {doc.get('_id')}")

        synced_doc_ids.append(doc["_id"])
        synced_count += 1

    verified_count = 0
    if synced_doc_ids:
        verified_count = mongo_client[DB_NAME][COLLECTION].count_documents(
            {"_id": {"$in": synced_doc_ids}, "syncedToNotion": True}
        )
        if verified_count != len(synced_doc_ids):
            raise RuntimeError(
                "Post-sync verification failed - not all updated docs have syncedToNotion=true"
            )

    print(f"Synced: {synced_count} | Skipped: {skipped_count} | Verified: {verified_count}")
    mongo_client.close()


if __name__ == "__main__":
    main()
