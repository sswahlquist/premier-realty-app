# CLAUDE.md — Stephen Wahlquist AI Consulting (Premier Realty App)

This file provides guidance to Claude Code when working with code in this repository.

## Project Overview

A Flask-based AI real estate web app for **Stephen Wahlquist**, a real estate agent in **Greenville, TX**.
Live URL: `https://premier-realty-app-production.up.railway.app`
GitHub: `https://github.com/sswahlquist/premier-realty-app.git` (branch: `main`)

Users get free AI-powered real estate tools (5 uses/day per tool). Paid users can download PDF reports via Stripe ($9.99).

---

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run locally
flask run
# or
python app.py

# Deploy: just push to main — Railway auto-deploys via GitHub
git push origin main
```

---

## Environment Variables

Set in Railway → service Variables. Required for full functionality:

| Variable | Purpose |
|---|---|
| `ANTHROPIC_API_KEY` | Claude AI (all AI features) |
| `STRIPE_SECRET_KEY` | PDF report payments ($9.99) |
| `RAPIDAPI_KEY` | Zillow Scraper API (real comps data) |
| `MAPBOX_TOKEN` | Geocoding + drive time routing |
| `RESEND_API_KEY` | Transactional email (contact form, appointments) |
| `FLASK_SECRET` | Flask session secret key |
| `DATA_DIR` | Set to `/data` when Railway Persistent Volume is mounted |
| `NOTIFICATION_EMAIL` | Where contact/appointment emails go (default: `s.s.wahlquist@gmail.com`) |
| `FROM_EMAIL` | Resend sender (default: `onboarding@resend.dev`) |
| `REPORT_PRICE_CENTS` | PDF price in cents (default: `999` = $9.99) |

---

## Architecture

Single-file Flask app: `app.py` (~2200 lines). All routes, helpers, and business logic are in this one file.

### Key Constants
```python
FREE_DAILY_LIMIT_PER_TOOL = 5        # Free uses per tool per day (per session)
AI_MODEL = "claude-sonnet-4-20250514" # Claude model for all AI features
CALENDLY_URL = "https://calendly.com/wahlquiststephen/30min"
```

### Persistent Storage
```python
DATA_DIR    = pathlib.Path(os.environ.get("DATA_DIR", "data"))
REPORTS_DIR = DATA_DIR / "reports"          # PDF reports saved here
APPOINTMENTS_FILE = DATA_DIR / "appointment_requests.txt"
CONTACT_LOG_FILE  = DATA_DIR / "contact_submissions.txt"
```
When `DATA_DIR=/data` and a Railway Persistent Volume is mounted at `/data`, all data survives redeploys.

### In-Memory Stores
```python
results_store: dict  # Valuation results keyed by UUID — lost on restart (by design)
chat_sessions: dict  # Alex chatbot history keyed by session ID
```

---

## Routes & Tools

| Route | Tool Name | `gate_json()` key |
|---|---|---|
| `GET /` | Homepage + valuation form | — |
| `POST /analyze` | AI property valuation | `"valuation"` |
| `GET /results/<id>` | Valuation results page | — |
| `GET /download/<id>` | PDF report download | — |
| `POST /create-checkout-session/<id>` | Stripe payment | — |
| `GET /comps` | Comps Finder page | — |
| `POST /api/comps` | Zillow comps data + AI fallback | `"comps"` |
| `GET /showings` | Showing Tour Planner page | — |
| `POST /api/showings/optimize` | Route optimization + Mapbox drive times | `"showings"` |
| `GET /listing` | Listing Generator page | — |
| `POST /api/listing` | AI listing description | `"listing"` |
| `GET /leads` | Lead Drafter page | — |
| `POST /leads/generate` | AI lead follow-up message | `"leads"` |
| `GET /deals` | Deal Analyzer page | — |
| `POST /deals/analyze` | AI deal analysis | `"deals"` |
| `GET /neighborhood` | Neighborhoods page | — |
| `POST /neighborhood/analyze` | AI neighborhood profile | `"neighborhood"` |
| `POST /neighborhood/compare` | AI neighborhood comparison | `"neighborhood_compare"` |
| `GET /calculator` | Mortgage Calculator page | — |
| `POST /calculator-chat` | AI mortgage chat | `"calculator"` |
| `GET /chat` | Full Alex chat page | — |
| `POST /api/chat` | Alex chatbot API | `"chat"` |
| `POST /contact` | Contact form submission | — |

---

## Key Patterns

### Daily Per-Tool Rate Limiting
Every AI endpoint uses the `@gate_json("tool_name")` decorator. The limit is tracked in Flask session cookies (`gen_counts` dict), resets at UTC midnight.

```python
@app.route("/api/comps", methods=["POST"])
@gate_json("comps")
def api_comps():
    ...
```

When limit is hit, returns JSON `{"error": "...", "limit_reached": True}` with HTTP 429.
The frontend intercepts this via a fetch interceptor in `base.html` and shows the upgrade modal.

### Geocoding (Mapbox → Nominatim fallback)
```python
_geocode_mapbox(address)  # Mapbox first (accurate)
_geocode(address)         # Mapbox with Nominatim fallback
```
Always use `_geocode()` for address lookups.

### Drive Times (Mapbox Directions API)
```python
_mapbox_directions(coords)  # Returns real road distances/times
_osrm_route(coords)         # OSRM fallback if Mapbox fails
```

### Comps Data (Zillow → AI fallback)
```python
_fetch_zillow_comps(address, beds, baths, sqft)
```
Tries multiple Zillow API endpoint paths. Falls back to Claude AI-generated comps if Zillow returns no data (rural areas like Greenville TX often have sparse Zillow data).

### Email (Resend)
```python
send_email(to, subject, html)       # Generic sender
_send_contact_email(name, email, phone, message)
_send_appointment_email(appt_dict)
```
All emails go to `NOTIFICATION_EMAIL` (Stephen's Gmail). No-ops gracefully if `RESEND_API_KEY` is missing.

### Watermark
Every AI-generated text output ends with:
```
Generated by Stephen Wahlquist AI Consulting — book a free call...
```
Applied via `WATERMARK` constant.

---

## File Structure

```
property_valuation_app/
├── app.py                    # Entire Flask application (~2200 lines)
├── requirements.txt          # Python dependencies
├── Procfile                  # Railway/Gunicorn: web: gunicorn app:app
├── railway.toml              # Railway config
├── CLAUDE.md                 # This file
├── static/
│   ├── style.css             # Main styles (dark navy + gold theme)
│   ├── neighborhood.css      # Neighborhood page styles
│   ├── calculator.js         # Mortgage calculator frontend logic
│   └── neighborhood.js       # Neighborhood comparison frontend
└── templates/
    ├── base.html             # Shared layout: navbar, Alex bubble, upgrade modal
    ├── index.html            # Homepage + valuation form
    ├── results.html          # Valuation results
    ├── comps.html            # Comps Finder
    ├── showings.html         # Tour Planner
    ├── listing.html          # Listing Generator
    ├── leads.html            # Lead Drafter
    ├── deals.html            # Deal Analyzer
    ├── neighborhood.html     # Neighborhood tools
    ├── calculator.html       # Mortgage Calculator
    ├── chat.html             # Full Alex chat experience
    ├── payment_success.html  # Post-Stripe redirect
    └── _upsell.html          # Upsell CTA partial (included in results.html)
```

---

## Deployment

- **Platform**: Railway (Hobby plan), US-West region
- **Process**: `gunicorn app:app` (Procfile)
- **Deploy trigger**: Push to `main` branch on GitHub → Railway auto-builds
- **Persistent Volume**: Mounted at `/data`, holds PDF reports + contact/appointment logs
- **External APIs**: Anthropic, Stripe, RapidAPI (Zillow), Mapbox, Resend

### Common Deploy Flow
```bash
git add <files>
git commit -m "description of change"
git push origin main
# Railway deploys in ~60 seconds
```

If push is rejected (fetch first):
```bash
git pull --rebase origin main
git push origin main
```

---

## Design System

- **Colors**: Navy `#1a2332`, Gold `#c8a97e`, White `#fff`
- **Fonts**: Merriweather (headings), Inter (body)
- **Theme**: Upscale real estate — dark, professional, trust-building
- **Mobile**: Fully responsive; hamburger menu in `base.html` exposes all tools

---

## Owner & Contact

- **Agent**: Stephen Wahlquist, Greenville TX
- **Email**: s.s.wahlquist@gmail.com
- **Calendly**: https://calendly.com/wahlquiststephen/30min
