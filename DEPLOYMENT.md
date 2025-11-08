# Deploying Backend to Render

This guide covers deploying the FastAPI backend to [Render](https://render.com).

## Prerequisites

1. A [Render account](https://dashboard.render.com/register)
2. Your code pushed to a Git repository (GitHub, GitLab, or Bitbucket)
3. (Optional) A PostgreSQL database for production use

## Deployment Options

Render supports two deployment methods:

### Option 1: Native Python Deployment (Recommended)

Uses Render's native Python runtime with the `render.yaml` Blueprint.

**Pros:**
- Faster builds
- Automatic zero-downtime deploys
- Easier configuration via Render dashboard

**Cons:**
- Less control over environment

### Option 2: Docker Deployment

Uses the custom `Dockerfile.production`.

**Pros:**
- Full control over environment
- Consistent with local Docker development
- Easy to test locally

**Cons:**
- Slower builds
- Requires Docker knowledge

---

## Option 1: Native Python Deployment

### Step 1: Prepare Your Repository

Ensure these files are in your repository:
- ✅ `render.yaml` - Service configuration
- ✅ `build.sh` - Build script
- ✅ `start.sh` - Start script
- ✅ `requirements.txt` - Python dependencies

### Step 2: Create PostgreSQL Database (Optional but Recommended)

1. Go to [Render Dashboard](https://dashboard.render.com)
2. Click **New** → **PostgreSQL**
3. Configure:
   - **Name**: `elearning-db`
   - **Database**: `elearning`
   - **User**: `elearning_user`
   - **Region**: Choose closest to your users
   - **Plan**: Start with **Free** tier
4. Click **Create Database**
5. Copy the **Internal Database URL** (starts with `postgresql://`)

### Step 3: Deploy Using Blueprint

1. Go to [Render Dashboard](https://dashboard.render.com)
2. Click **New** → **Blueprint**
3. Connect your Git repository
4. Render will detect `render.yaml` automatically
5. Review the services:
   - **Web Service**: `elearning-backend`
   - **Database**: `elearning-db` (if included)
6. Update environment variables:
   - `CORS_ORIGINS`: Your frontend URL(s)
   - `DATABASE_URL`: Will auto-populate if using Render PostgreSQL
7. Click **Apply**

### Step 4: Configure Environment Variables

After deployment, add/update these in the Render Dashboard:

#### Required Variables
```bash
ENVIRONMENT=production
AUTO_MIGRATE=true
DATABASE_URL=<your-database-url>  # Auto-set if using Render PostgreSQL
CORS_ORIGINS=https://yourfrontend.com,https://www.yourfrontend.com
```

#### Optional Variables
```bash
PORT=8000                  # Render sets this automatically
WORKERS=4                  # Number of gunicorn workers
TIMEOUT=120               # Request timeout in seconds
LOG_LEVEL=info            # Logging level (debug/info/warning/error)
EXPORT_HEADERS=1          # Enable export headers feature
```

### Step 5: Verify Deployment

1. Wait for build to complete (5-10 minutes first time)
2. Visit your service URL: `https://elearning-backend-xxxx.onrender.com`
3. Check health endpoint: `https://your-service.onrender.com/api/v1/health`
4. Visit API docs: `https://your-service.onrender.com/docs`

---

## Option 2: Docker Deployment

### Step 1: Test Docker Build Locally

```bash
# Build production image
docker build -f Dockerfile.production -t elearning-backend:prod .

# Run locally to test
docker run -p 8000:8000 \
  -e DATABASE_URL="sqlite+aiosqlite:///./data/elearning.db" \
  -e CORS_ORIGINS="http://localhost:3000" \
  elearning-backend:prod

# Test health endpoint
curl http://localhost:8000/api/v1/health
```

### Step 2: Create Web Service on Render

1. Go to [Render Dashboard](https://dashboard.render.com)
2. Click **New** → **Web Service**
3. Connect your Git repository
4. Configure:
   - **Name**: `elearning-backend`
   - **Region**: Choose closest to your users
   - **Branch**: `main` (or your production branch)
   - **Runtime**: **Docker**
   - **Dockerfile Path**: `Dockerfile.production`
   - **Docker Build Context Directory**: `.` (root)
5. **Advanced Settings**:
   - **Health Check Path**: `/api/v1/health`
   - **Auto-Deploy**: Yes (for automatic deploys on git push)

### Step 3: Set Environment Variables

Same as Option 1 - Step 4 above.

### Step 4: Deploy

1. Click **Create Web Service**
2. Render will build and deploy automatically
3. Monitor build logs for any issues

---

## Database Configuration

### Using SQLite (Simple, Not Recommended for Production)

SQLite works but has limitations:
- No concurrent writes
- Data persists in `/data` directory (use Render Disks)

**Environment variable:**
```bash
DATABASE_URL=sqlite+aiosqlite:///./data/elearning.db
```

**Add a Render Disk:**
1. Go to your service → **Settings** → **Disks**
2. Click **Add Disk**
3. **Name**: `data`
4. **Mount Path**: `/app/data`
5. **Size**: 1 GB (free tier)

### Using PostgreSQL (Recommended for Production)

PostgreSQL is better for production:
- Concurrent access
- Better performance
- Managed backups

**Setup:**
1. Create PostgreSQL database (see Option 1 - Step 2)
2. Use the Internal Database URL in `DATABASE_URL`
3. Update connection string format:
   ```bash
   DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/dbname
   ```

**Migration:**
Migrations run automatically if `AUTO_MIGRATE=true`:
```bash
alembic upgrade head
```

---

## Monitoring & Logs

### View Logs
1. Go to your service in Render Dashboard
2. Click **Logs** tab
3. Monitor application startup, requests, errors

### Health Checks
Render automatically monitors `/api/v1/health`:
- **Healthy**: Returns 200 status
- **Unhealthy**: Service restarts automatically

### Metrics
Available in Render Dashboard:
- CPU usage
- Memory usage
- Request count
- Response times

---

## Common Issues & Troubleshooting

### Build Failures

**Issue**: `alembic upgrade head` fails
```bash
# Solution: Check DATABASE_URL is set correctly
# Ensure database exists and is accessible
```

**Issue**: Package installation fails
```bash
# Solution: Check requirements.txt for version conflicts
# Try pinning specific versions
```

### Runtime Issues

**Issue**: 502 Bad Gateway
```bash
# Check logs for startup errors
# Ensure PORT environment variable is used
# Verify health check endpoint works
```

**Issue**: Database connection errors
```bash
# Verify DATABASE_URL format
# For PostgreSQL: postgresql+asyncpg://...
# For SQLite: sqlite+aiosqlite:///./data/elearning.db
```

**Issue**: CORS errors
```bash
# Update CORS_ORIGINS with correct frontend URLs
# Include both www and non-www versions
# Use https:// in production
```

---

## Performance Optimization

### Adjust Workers

For better performance, tune worker count based on your plan:

```bash
# Free tier: 512 MB RAM
WORKERS=2

# Starter tier: 2 GB RAM
WORKERS=4

# Standard tier: 4 GB RAM
WORKERS=8
```

**Rule of thumb**: `WORKERS = (2 × CPU cores) + 1`

### Caching

Consider adding Redis for caching:
1. Create Redis instance on Render
2. Install `redis` and `aioredis` packages
3. Update code to cache frequently accessed data

---

## Updating Your Deployment

### Automatic Deploys
With Auto-Deploy enabled, Render automatically deploys when you:
1. Push to your production branch
2. Merge pull requests

### Manual Deploys
1. Go to service in Render Dashboard
2. Click **Manual Deploy** → **Deploy latest commit**

### Rollbacks
1. Go to service → **Events** tab
2. Find previous successful deploy
3. Click **Rollback to this deploy**

---

## Environment-Specific Configuration

### Development
```bash
ENVIRONMENT=development
DEBUG=true
AUTO_MIGRATE=false
```

### Staging
```bash
ENVIRONMENT=staging
AUTO_MIGRATE=true
CORS_ORIGINS=https://staging.yourfrontend.com
```

### Production
```bash
ENVIRONMENT=production
AUTO_MIGRATE=true
CORS_ORIGINS=https://yourfrontend.com,https://www.yourfrontend.com
```

---

## Security Checklist

- [ ] Use PostgreSQL instead of SQLite
- [ ] Set strong database password
- [ ] Use environment variables for secrets
- [ ] Enable HTTPS only (Render provides free SSL)
- [ ] Restrict CORS_ORIGINS to your domains
- [ ] Review and minimize exposed API endpoints
- [ ] Enable rate limiting (add middleware)
- [ ] Regular dependency updates
- [ ] Monitor error logs for suspicious activity

---

## Cost Optimization

### Free Tier Limits
- **Web Service**: 750 hours/month (sleeps after 15 min inactivity)
- **PostgreSQL**: 90-day expiration, 1GB storage
- **Bandwidth**: 100 GB/month

### Tips to Stay Free
1. Use single web service
2. Optimize database queries
3. Enable Auto-Deploy to avoid manual rebuilds
4. Use Render's free PostgreSQL if database is small

### Upgrading
When you outgrow free tier:
- **Starter ($7/month)**: Always-on service, more resources
- **Standard ($25/month)**: Better performance, scaling

---

## Support & Resources

- [Render Documentation](https://render.com/docs)
- [Render Status Page](https://status.render.com)
- [Render Community](https://community.render.com)
- [FastAPI Deployment Guide](https://fastapi.tiangolo.com/deployment/)

---

## Quick Start Checklist

- [ ] Push code to Git repository
- [ ] Create Render account
- [ ] (Optional) Create PostgreSQL database
- [ ] Deploy using Blueprint or Docker
- [ ] Set environment variables
- [ ] Test health endpoint
- [ ] Verify API documentation
- [ ] Update frontend to use production API URL
- [ ] Monitor logs for errors
- [ ] Test SCORM export functionality

---

## Next Steps

1. **Custom Domain**: Add your own domain in Render settings
2. **Monitoring**: Set up error tracking (Sentry)
3. **CI/CD**: Add GitHub Actions for automated testing
4. **Backups**: Schedule database backups
5. **Performance**: Add caching and optimize queries
