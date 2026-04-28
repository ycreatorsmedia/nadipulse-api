# NādiPulse Telugu News API

Scrapes Eenadu, AndhraJyothi, Sakshi, TV9, NTV, 10TV every 15 minutes.
Serves clean JSON API for your NādiPulse website.

## Deploy to Render.com (Free)

1. Push this folder to a NEW GitHub repo called `nadipulse-api`
2. Go to render.com → New → Web Service
3. Connect your GitHub → select `nadipulse-api`
4. Settings:
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
5. Click Deploy
6. Your API URL: `https://nadipulse-api.onrender.com`

## API Endpoints

- GET /news — all articles
- GET /news?source=Sakshi — filter by source
- GET /news?bias=YSRCP+Pro — filter by bias
- GET /health — check status
