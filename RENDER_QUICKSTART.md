# Render Deployment Quick Reference

## 🚀 Quick Deploy (Blueprint Method)

1. **Push code to Git** with `render.yaml`
2. **Render Dashboard** → New → Blueprint
3. **Connect repository** and apply
4. **Set env vars**: `CORS_ORIGINS`, `DATABASE_URL`
5. **Done!** Check `https://your-service.onrender.com/docs`

## 📋 Required Files

```
backend/
├── render.yaml              # Render service config
├── build.sh                 # Build script (chmod +x)
├── start.sh                 # Start script (chmod +x)
├── Dockerfile.production    # Docker config (alternative)
└── requirements.txt         # Python dependencies
```

## 🔧 Essential Environment Variables

```bash
# Required
ENVIRONMENT=production
DATABASE_URL=<postgres-or-sqlite-url>
CORS_ORIGINS=https://yourfrontend.com

# Optional
AUTO_MIGRATE=true           # Auto-run migrations
WORKERS=4                   # Gunicorn workers
PORT=8000                   # Render sets this
```

## 🗄️ Database Options

### SQLite (Simple)
```bash
DATABASE_URL=sqlite+aiosqlite:///./data/elearning.db
# Add Render Disk: /app/data
```

### PostgreSQL (Recommended)
```bash
DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/db
# Create via: New → PostgreSQL
```

## 🔍 Testing Locally

```bash
# Test build script
./build.sh

# Test with gunicorn
gunicorn app.main:app --workers 4 --worker-class uvicorn.workers.UvicornWorker

# Test Docker image
docker build -f Dockerfile.production -t backend:prod .
docker run -p 8000:8000 -e DATABASE_URL="..." backend:prod
```

## 🩺 Health Check Endpoints

- **Health**: `/api/v1/health`
- **Docs**: `/docs`
- **ReDoc**: `/redoc`
- **Root**: `/` (returns API info)

## 📊 Monitoring

```bash
# View logs
Render Dashboard → Your Service → Logs

# Check metrics
Dashboard → Metrics (CPU, Memory, Requests)

# Health status
Dashboard → Events (deploy history, health checks)
```

## 🐛 Common Issues

| Issue | Solution |
|-------|----------|
| 502 Bad Gateway | Check logs, verify `PORT` env var used |
| Build fails | Check `requirements.txt`, run `./build.sh` locally |
| DB connection error | Verify `DATABASE_URL` format matches DB type |
| CORS error | Add frontend URL to `CORS_ORIGINS` |
| Migration fails | Check DB permissions, manually run `alembic upgrade head` |

## 🔄 Deploy Updates

**Auto-deploy**: Push to main branch → Render deploys automatically

**Manual deploy**: 
1. Dashboard → Your Service
2. Manual Deploy → Deploy latest commit

**Rollback**:
1. Dashboard → Events
2. Find previous deploy → Rollback

## 💰 Free Tier Limits

- ⏰ 750 hours/month (sleeps after 15 min inactive)
- 💾 PostgreSQL expires after 90 days
- 🌐 100 GB bandwidth/month
- 📦 1 GB disk storage

## 📈 Performance Tuning

```bash
# Adjust workers by RAM
# Free (512MB): WORKERS=2
# Starter (2GB): WORKERS=4
# Standard (4GB): WORKERS=8

# Timeout for long requests
TIMEOUT=120

# Logging
LOG_LEVEL=info  # debug/info/warning/error
```

## 🔐 Security Checklist

- [ ] Use PostgreSQL (not SQLite) in production
- [ ] Restrict `CORS_ORIGINS` to your domains
- [ ] Use HTTPS (automatic on Render)
- [ ] Set strong DB password
- [ ] Keep dependencies updated
- [ ] Monitor error logs

## 🆘 Getting Help

- 📖 Full guide: `DEPLOYMENT.md`
- 🌐 Render Docs: https://render.com/docs
- 💬 Community: https://community.render.com
- 📊 Status: https://status.render.com

## ⚡ Zero to Deploy (5 minutes)

```bash
# 1. Ensure scripts are executable
chmod +x build.sh start.sh

# 2. Test locally (optional)
./build.sh && ./start.sh

# 3. Push to Git
git add .
git commit -m "Add Render deployment config"
git push

# 4. Deploy on Render
# - Go to https://dashboard.render.com
# - New → Blueprint
# - Connect repo
# - Apply!

# 5. Set CORS_ORIGINS
# Dashboard → Service → Environment
# Add: CORS_ORIGINS=https://yourfrontend.com

# 6. Visit your API
# https://your-service.onrender.com/docs
```

---

**Pro Tip**: Test the entire deployment flow locally using Docker before deploying to Render to catch issues early!
