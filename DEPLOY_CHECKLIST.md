# 🎯 Pre-Deployment Checklist

Use this checklist before deploying to Render to ensure everything is ready.

## 📋 Code Preparation

### Required Files
- [ ] `render.yaml` exists and configured
- [ ] `build.sh` exists and is executable (`chmod +x build.sh`)
- [ ] `start.sh` exists and is executable (`chmod +x start.sh`)
- [ ] `requirements.txt` has all dependencies
- [ ] `alembic.ini` and migrations exist in `alembic/versions/`
- [ ] `.dockerignore` updated (excludes test files, .env, etc.)

### Code Quality
- [ ] All tests pass locally (`pytest`)
- [ ] No syntax errors (`python -m py_compile app/**/*.py`)
- [ ] Migrations apply cleanly (`alembic upgrade head`)
- [ ] App starts without errors (`python -m app.main` or `uvicorn app.main:app`)

### Environment Configuration
- [ ] `.env.example` created with all required variables
- [ ] No hardcoded secrets or credentials in code
- [ ] `PORT` environment variable used (not hardcoded)
- [ ] Database URL uses environment variable

## 🧪 Local Testing

### Build Script
```bash
# Test build process
./build.sh

# Expected output:
# - Dependencies installed
# - Gunicorn installed
# - Migrations run successfully
# - No errors
```
- [ ] Build script runs without errors
- [ ] All dependencies install successfully
- [ ] Migrations complete

### Start Script
```bash
# Test production server
export DATABASE_URL="sqlite+aiosqlite:///./data/elearning.db"
export CORS_ORIGINS="http://localhost:3000"
export ENVIRONMENT=production
./start.sh

# In another terminal:
curl http://localhost:8000/api/v1/health
curl http://localhost:8000/docs
```
- [ ] Server starts on PORT (default 8000)
- [ ] Health endpoint returns 200
- [ ] API docs accessible
- [ ] No startup errors in logs

### Docker Build (Optional)
```bash
docker build -f Dockerfile.production -t backend-test .
docker run -p 8000:8000 \
  -e DATABASE_URL="sqlite+aiosqlite:///./data/elearning.db" \
  -e CORS_ORIGINS="http://localhost:3000" \
  backend-test

curl http://localhost:8000/api/v1/health
```
- [ ] Docker image builds successfully
- [ ] Container runs without errors
- [ ] Health check passes

## 🗄️ Database Preparation

### SQLite (Development/Testing)
- [ ] `data/` directory created
- [ ] Will create Render Disk for persistent storage
- [ ] Understand limitations (no concurrent writes)

### PostgreSQL (Recommended Production)
- [ ] PostgreSQL database created on Render
- [ ] Database URL copied (starts with `postgresql://`)
- [ ] Connection string format: `postgresql+asyncpg://user:pass@host:5432/db`
- [ ] Database accessible from Render (use Internal URL)

### Migrations
- [ ] All migration files in `alembic/versions/`
- [ ] Migrations apply successfully locally
- [ ] No conflicting migrations
- [ ] `AUTO_MIGRATE=true` set for automatic migration on deploy

## 🔒 Security Review

### Credentials
- [ ] No secrets committed to Git
- [ ] `.env` in `.gitignore`
- [ ] Database passwords are strong
- [ ] API keys stored as environment variables

### CORS Configuration
- [ ] `CORS_ORIGINS` set to actual frontend URLs
- [ ] No wildcards (`*`) in production
- [ ] Both `www` and non-`www` versions included if needed
- [ ] Only HTTPS URLs (except localhost for testing)

### API Security
- [ ] Input validation on all endpoints
- [ ] File upload size limits enforced
- [ ] Error messages don't leak sensitive info
- [ ] Rate limiting considered (if needed)

## 🌐 Render Configuration

### Account Setup
- [ ] Render account created
- [ ] Payment method added (if using paid tier)
- [ ] GitHub/GitLab/Bitbucket connected

### Service Configuration
- [ ] Service name chosen (e.g., `elearning-backend`)
- [ ] Region selected (closest to users)
- [ ] Plan selected (Free/Starter/Standard)
- [ ] Auto-deploy enabled for main branch

### Environment Variables
Prepare these values (add in Render Dashboard after deployment):

**Required:**
```
ENVIRONMENT=production
CORS_ORIGINS=https://yourfrontend.com
```

**Database:**
```
DATABASE_URL=<from-render-postgres-or-custom>
```

**Optional:**
```
AUTO_MIGRATE=true
WORKERS=4
TIMEOUT=120
LOG_LEVEL=info
EXPORT_HEADERS=1
```

- [ ] All required environment variables identified
- [ ] Values prepared and documented
- [ ] Understand which are set automatically by Render

## 📦 Git Repository

### Code Push
- [ ] All deployment files committed
- [ ] Code pushed to main/production branch
- [ ] Repository accessible to Render
- [ ] No large files (>100MB) committed

### GitHub Actions (Optional)
If using CI/CD workflow:
- [ ] `.github/workflows/ci-cd.yml` configured
- [ ] GitHub secrets added (`RENDER_DEPLOY_HOOK_URL`)
- [ ] Workflow runs successfully

## 🚀 Deployment Strategy

### First Deployment
- [ ] Choose deployment method (Blueprint vs Manual)
- [ ] Understand free tier limitations
- [ ] Plan for service sleep on free tier
- [ ] Database expiration understood (90 days free)

### Monitoring Setup
- [ ] Know where to view logs (Render Dashboard)
- [ ] Health check endpoint configured (`/api/v1/health`)
- [ ] Error notification preferences set
- [ ] Monitoring plan (if using external tools)

## ✅ Pre-Deploy Testing Matrix

| Test | Command | Expected Result | Status |
|------|---------|-----------------|--------|
| Build | `./build.sh` | Success, no errors | [ ] |
| Start | `./start.sh` | Server starts on PORT | [ ] |
| Health | `curl localhost:8000/api/v1/health` | 200 OK response | [ ] |
| Docs | Visit `localhost:8000/docs` | Swagger UI loads | [ ] |
| Course Create | POST to `/api/v1/courses` | Creates course | [ ] |
| Course Export | POST to `/api/v1/export` | Returns SCORM zip | [ ] |
| Docker Build | `docker build -f Dockerfile.production` | Image builds | [ ] |
| Docker Run | `docker run backend-test` | Container starts | [ ] |
| Migrations | `alembic upgrade head` | Applies cleanly | [ ] |
| Tests | `pytest` | All tests pass | [ ] |

## 📝 Deployment Day Checklist

### Before Deploy
- [ ] All items above checked
- [ ] Team notified
- [ ] Backup of current data (if applicable)
- [ ] Maintenance window scheduled (if needed)

### During Deploy
- [ ] Monitor build logs in Render
- [ ] Verify migrations complete
- [ ] Check for startup errors
- [ ] Test health endpoint immediately

### After Deploy
- [ ] Health endpoint returns 200
- [ ] API documentation accessible
- [ ] Test critical endpoints (create course, export)
- [ ] Frontend can connect
- [ ] CORS working correctly
- [ ] Database connection verified
- [ ] No errors in logs
- [ ] Performance acceptable

### Rollback Plan
- [ ] Know how to rollback (Render Events → Previous deploy)
- [ ] Database backup exists (if using PostgreSQL)
- [ ] Previous build still available

## 🎉 Post-Deployment

### Verification
- [ ] Run smoke tests on production URL
- [ ] Check all API endpoints
- [ ] Test SCORM export functionality
- [ ] Verify frontend integration
- [ ] Monitor logs for 24 hours

### Documentation
- [ ] Update team with production URL
- [ ] Document any deployment issues
- [ ] Update runbook if needed

### Optimization
- [ ] Review initial performance
- [ ] Adjust worker count if needed
- [ ] Consider caching strategy
- [ ] Plan for scaling if needed

## 🆘 Common Pre-Deploy Issues

| Issue | Solution |
|-------|----------|
| Build script fails locally | Fix before deploying - test `./build.sh` |
| Tests failing | Fix tests first - run `pytest` |
| Migration conflicts | Resolve locally with `alembic` |
| Missing dependencies | Add to `requirements.txt` |
| CORS not working | Check `CORS_ORIGINS` format |
| Port hardcoded | Use `os.getenv("PORT", 8000)` |
| Secrets in code | Move to environment variables |
| Large files committed | Remove and add to `.gitignore` |

## 📚 References

- **Quick Start**: `RENDER_QUICKSTART.md`
- **Full Guide**: `DEPLOYMENT.md`
- **Setup Summary**: `DEPLOY_README.md`
- **Render Docs**: https://render.com/docs

---

**Status**: Ready to deploy? ✅ All items checked above = Good to go! 🚀

**Not ready?** ❌ Fix failing items before deploying to avoid issues.
