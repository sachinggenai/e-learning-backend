# US-PREREQ-003: Deploy MinIO (S3-Compatible Storage) via Docker for Local Development

| Field | Value |
|-------|-------|
| **Type** | 🏗️ Infrastructure Pre-Requisite |
| **Priority** | 🟡 HIGH — Unblocks US-PEND-012 (SCORM persistent storage) |
| **Depends On** | Docker Desktop (running on developer machine) |
| **Estimated Effort** | 10 minutes |
| **Unblocks** | US-PEND-012 Part B (SCORM export persistent storage), future S3 migration |

---

## User Story

**As a** backend developer implementing persistent file storage,
**I want** an S3-compatible object store running locally in Docker,
**So that** I can store SCORM packages, uploaded files, and assets without a cloud S3 account.

---

## Intent of Work

Deploy **MinIO** — the most widely adopted open-source S3-compatible object storage (Apache 2.0 license, 50k+ GitHub stars). MinIO implements the full AWS S3 API, so any S3 SDK works unchanged. Runs as a single binary in Docker.

**Why MinIO over alternatives:**
- **MinIO vs local filesystem:** S3 API means zero code change when migrating to AWS S3 in production. `boto3` / `aioboto3` works against both.
- **MinIO vs SeaweedFS:** Larger community, better documentation, built-in web console.
- **MinIO vs LocalStack:** MinIO is purpose-built for object storage; LocalStack emulates 50+ AWS services (heavier).

---

## Docker Deployment

### One-Command Install

```powershell
# PowerShell — run directly on Windows (as provided by user)
docker run -d `
  -p 9000:9000 `
  -p 9001:9001 `
  --name minio-local `
  -v minio_data:/data `
  -e "MINIO_ROOT_USER=ROOTUSER" `
  -e "MINIO_ROOT_PASSWORD=CHANGEME123" `
  minio/minio server /data --console-address ":9001"
```

### What Each Flag Means

| Flag | Value | Purpose |
|------|-------|---------|
| `-p 9000:9000` | S3 API port | Connect your app to `http://localhost:9000` |
| `-p 9001:9001` | Web Console | Admin UI at `http://localhost:9001` |
| `-v minio_data:/data` | Persistent volume | All stored objects survive container restart |
| `MINIO_ROOT_USER` | Admin username | Default: `ROOTUSER` |
| `MINIO_ROOT_PASSWORD` | Admin password | Default: `CHANGEME123` |
| `--console-address ":9001"` | Console port binding | Web UI at port 9001 |

---

## Post-Install Setup

### Step 1: Access Web Console

```
URL:      http://localhost:9001
Username: ROOTUSER
Password: CHANGEME123
```

### Step 2: Create Bucket via Web Console

1. Open http://localhost:9001
2. Login with ROOTUSER / CHANGEME123
3. Click **"Create a Bucket"**
4. Name: `elearning-assets`
5. Click **"Create Bucket"**

### Step 3: Set Bucket Policy (Public Download)

In the MinIO Console, go to Buckets → `elearning-assets` → Anonymous → Add Access Rule:
```
Prefix: /
Access:  readonly
```

### Step 4: Create Access Key for Application

In the MinIO Console, go to Access Keys → Create access key:
```
Access Key: elearning_app
Secret Key: elearning_app_secret_32_chars_min
```
Copy these into your `.env` file.

---

## Verification

```powershell
# 1. Check MinIO is running
docker ps --filter name=minio-local

# 2. Check health endpoint
curl http://localhost:9000/minio/health/live
# Expected: (empty 200 OK response)

# 3. Install MinIO client (mc) — optional but useful
docker exec minio-local mc alias set local http://localhost:9000 ROOTUSER CHANGEME123

# 4. Create bucket via CLI
docker exec minio-local mc mb local/elearning-assets
# Expected: Bucket created successfully 'local/elearning-assets'

# 5. List buckets
docker exec minio-local mc ls local
# Expected: elearning-assets

# 6. Upload a test file
echo "test content" > test.txt
docker cp test.txt minio-local:/tmp/
docker exec minio-local mc cp /tmp/test.txt local/elearning-assets/
docker exec minio-local mc ls local/elearning-assets/
# Expected: test.txt
```

---

## Python Verification (After `pip install boto3`)

```python
# test_minio.py — verify Python → MinIO connectivity
import boto3
from botocore.client import Config

# Connect to MinIO (same API as AWS S3)
s3 = boto3.client(
    "s3",
    endpoint_url="http://localhost:9000",
    aws_access_key_id="ROOTUSER",
    aws_secret_access_key="CHANGEME123",
    config=Config(signature_version="s3v4"),
    region_name="us-east-1",
)

# Create bucket
try:
    s3.create_bucket(Bucket="elearning-assets")
    print("✅ Bucket created: elearning-assets")
except s3.exceptions.BucketAlreadyOwnedByYou:
    print("✅ Bucket exists: elearning-assets")

# Upload file
s3.put_object(
    Bucket="elearning-assets",
    Key="test/hello.txt",
    Body="Hello from e-learning-backend!",
    ContentType="text/plain",
)
print("✅ Upload: OK")

# Download file
obj = s3.get_object(Bucket="elearning-assets", Key="test/hello.txt")
content = obj["Body"].read().decode("utf-8")
print(f"✅ Download: {content}")

# List objects
resp = s3.list_objects_v2(Bucket="elearning-assets")
for item in resp.get("Contents", []):
    print(f"   {item['Key']} ({item['Size']} bytes)")
```

---

## Teardown

```powershell
# Stop and remove (data preserved in volume)
docker stop minio-local
docker rm minio-local

# Remove data volume (fresh start)
docker volume rm minio_data
```

---

## Environment Variables (add to `.env`)

```bash
# MinIO / S3-compatible storage
S3_ENDPOINT=http://localhost:9000
S3_ACCESS_KEY=ROOTUSER
S3_SECRET_KEY=CHANGEME123
S3_BUCKET=elearning-assets
S3_REGION=us-east-1
```

---

## Acceptance Criteria

| # | Criterion | Verification |
|---|-----------|-------------|
| AC-1 | MinIO container running | `docker ps --filter name=minio-local` |
| AC-2 | Health endpoint responds | `curl http://localhost:9000/minio/health/live` → 200 OK |
| AC-3 | Bucket `elearning-assets` created | `docker exec minio-local mc ls local` |
| AC-4 | Python boto3 connects and uploads/downloads | Run `test_minio.py` → all ✅ |
| AC-5 | Console accessible | Open http://localhost:9001 → login with ROOTUSER/CHANGEME123 |

---

## Stories Unblocked

Once this pre-requisite is complete:

| Story | What It Needs MinIO For |
|-------|------------------------|
| **US-PEND-012** | SCORM ZIP persistent storage via S3 API; `download_url` becomes real HTTP URL |
