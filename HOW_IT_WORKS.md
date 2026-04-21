# How MongoDB to Notion Sync Works

This document explains how the automation works from start to finish.

## What This Project Does

The project moves new MongoDB records into a Notion database on a schedule using GitHub Actions.

It is designed to:
- sync only new records
- avoid duplicates
- validate Notion schema before writing
- run without a server

## Files and Responsibilities

- `sync_script.py`
  - reads secrets from environment variables
  - fetches unsynced MongoDB records
  - parses and normalizes dates
  - creates Notion pages
  - marks MongoDB records as synced
  - verifies synced flags after update

- `.github/workflows/sync.yml`
  - runs the script on a schedule and on manual trigger
  - installs dependencies
  - injects secrets into runtime environment

- `requirements.txt`
  - Python packages needed by the sync script

## Required Secrets

Set these in GitHub repository settings:

Settings -> Secrets and variables -> Actions -> Repository secrets

- `MONGO_URI`
- `NOTION_TOKEN`
- `NOTION_DB_ID`

## Runtime Flow

Every run follows this sequence:

1. GitHub Actions starts the workflow (scheduled or manual).
2. Runner checks out the repository.
3. Runner installs dependencies from `requirements.txt`.
4. Runner executes `sync_script.py` with injected secrets.
5. Script validates Notion database properties and types.
6. Script queries MongoDB for documents where `syncedToNotion != true`.
7. For each document:
   - parse source and end dates
   - skip if required dates are invalid
   - create a page in Notion
   - set `syncedToNotion: true` in MongoDB
8. Script verifies all updated records are actually marked synced.
9. Script prints summary counts: synced, skipped, verified.
10. Workflow ends and logs remain in GitHub Actions.

## Why Duplicates Are Prevented

The query only pulls documents that are not marked as synced:

- filter condition: `{"syncedToNotion": {"$ne": True}}`

After successful Notion insert, the same MongoDB document is updated:

- update: `{"$set": {"syncedToNotion": True}}`

Future runs ignore those records, so duplicates are not created.

## Notion Schema Requirement

Before syncing, the script checks that your Notion database has these exact properties:

- `SourceBatchNum` type `title`
- `BatchNum` type `rich_text`
- `SourceVesselSize` type `number`
- `NewVesselSize` type `number`
- `Start Date` type `date`
- `End Date` type `date`

If any are missing or wrong type, the run fails early with a clear error.

## Scheduling

Current workflow schedule is every 30 minutes (UTC):

- cron: `*/30 * * * *`

This can also be triggered manually from the Actions tab.

## Monitoring and Validation

Use GitHub Actions logs to confirm each run:

- Notion schema validation passed
- summary line with synced, skipped, verified counts

You can also validate in MongoDB directly:

- synced records should contain `syncedToNotion: true`
- reruns should not recreate already synced items

## Common Failure Points

- missing GitHub secret values
- Notion database property names/types do not match
- MongoDB connection string invalid
- date parsing fails for incoming data format

## Quick Operations Checklist

1. Confirm required secrets exist in GitHub.
2. Run workflow manually once.
3. Check logs for schema validation and summary counts.
4. Confirm records appear in Notion.
5. Confirm MongoDB records are marked `syncedToNotion: true`.
6. Leave schedule enabled for automatic sync.
