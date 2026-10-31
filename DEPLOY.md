# Deployment Guide

## Local Development

### 1. Setup
```bash
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Run Server
```bash
python -m app.main
```

Server runs on http://localhost:8000

### 3. Access UI
- **Upload:** http://localhost:8000/
- **Transactions:** http://localhost:8000/transactions
- **Analysis:** http://localhost:8000/analysis
- **API Docs:** http://localhost:8000/docs

### 4. Database
- SQLite by default: `statements.db`
- Reset with: `curl -X POST http://localhost:8000/api/reset`

---

## Render.com (Recommended for Level 1)

### 1. Push to GitHub
```bash
git init
git add .
git commit -m "Initial commit"
git remote add origin <your-repo>
git push -u origin main
```

### 2. Create Render Web Service
- Go to https://render.com/
- New → Web Service
- Connect GitHub repo
- Settings:
  - **Runtime:** Python 3.11
  - **Build Command:** `pip install -r requirements.txt`
  - **Start Command:** `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
  - **Environment Variables:**
    - `DATABASE_URL=sqlite:///./statements.db` (or PostgreSQL)

### 3. Deploy
- Click "Create Web Service"
- Render will auto-deploy on push

---

## Railway.app (Alternative)

### 1. Install Railway CLI
```bash
npm i -g @railway/cli
```

### 2. Login & Deploy
```bash
railway login
railway init
railway up
```

### 3. Set Environment
```bash
railway variables set DATABASE_URL=sqlite:///./statements.db
```

---

## Heroku (Legacy)

### 1. Install Heroku CLI
```bash
brew install heroku/brew/heroku  # macOS
# Windows: https://devcenter.heroku.com/articles/heroku-cli
```

### 2. Create Procfile
```
web: uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

### 3. Deploy
```bash
heroku login
heroku create <app-name>
git push heroku main
```

---

## Docker (For Advanced Users)

### Create Dockerfile
```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### Build & Run
```bash
docker build -t bank-analyzer .
docker run -p 8000:8000 bank-analyzer
```

---

## Database Setup (PostgreSQL for Scale)

### Local PostgreSQL
```bash
# Install PostgreSQL
# Create database
createdb azentio_crew

# Set env var
export DATABASE_URL=postgresql://user:password@localhost/azentio_crew

# Run app
python -m app.main
```

### Render PostgreSQL
1. Create PostgreSQL database on Render
2. Copy `DATABASE_URL` from dashboard
3. Set in web service environment variables

### Railway PostgreSQL
```bash
railway add postgresql
railway variables set DATABASE_URL=$DATABASE_URL
```

---

## Netlify (Frontend Only - Not Recommended)

Bank Analyzer is a full-stack app with a FastAPI backend. Netlify cannot host the backend. 

**Use Render/Railway instead** for complete deployment.

If you need a separate static frontend:
1. Build a React/Vue app
2. Point API to Render/Railway backend
3. Deploy frontend to Netlify

---

## Deployment Checklist

- [ ] Code committed to git
- [ ] `requirements.txt` updated
- [ ] Environment variables set (DATABASE_URL, etc.)
- [ ] Tests pass locally
- [ ] README.md up to date
- [ ] No secrets in code
- [ ] Database initialized
- [ ] Startup command correct
- [ ] Port binding correct (0.0.0.0, not localhost)

---

## Monitoring

### Logs
```bash
# Render
render logs

# Railway
railway logs

# Heroku
heroku logs --tail
```

### Health Check
```bash
curl https://<your-domain>/health
# Should return: {"status": "ok"}
```

---

## Troubleshooting

### Port Already in Use
```bash
# Find process on port 8000
lsof -i :8000

# Kill it
kill -9 <PID>
```

### Database Issues
```bash
# Check DATABASE_URL
echo $DATABASE_URL

# Reset database
curl -X POST http://localhost:8000/api/reset
```

### Dependencies
```bash
# Update requirements.txt
pip freeze > requirements.txt

# Reinstall
pip install -r requirements.txt --force-reinstall
```

---

## Performance Tips

1. **Use PostgreSQL** for >10k transactions
2. **Index txn_date** and account_id in database
3. **Cache metrics** with TTL (add Redis later)
4. **Batch uploads** instead of single files
5. **Monitor memory** usage with large PDFs

---

## Security (Level 2+)

- [ ] Add authentication (OAuth/JWT)
- [ ] Encrypt database
- [ ] Use HTTPS only
- [ ] Rate limiting on API
- [ ] Input validation
- [ ] CORS configuration
- [ ] Secret management

---

**Next Steps:**
1. Deploy to Render/Railway
2. Test uploads & classification
3. Share link with team
4. Collect feedback
5. Plan Level 2 features

