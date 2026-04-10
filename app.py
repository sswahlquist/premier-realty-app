"""
property_valuation_app — Stephen Wahlquist AI Consulting
Flask web app that uses Claude to generate AI property valuations.
"""

import os
import uuid
import json
import io
import re
import math
import pathlib
from datetime import datetime

import requests
from flask import Flask, render_template, request, redirect, url_for, session, send_file, flash, jsonify

import anthropic
import stripe

stripe.api_key    = os.environ.get("STRIPE_SECRET_KEY", "")
RAPIDAPI_KEY      = os.environ.get("RAPIDAPI_KEY", "")
REPORT_PRICE_CENTS = int(os.environ.get("REPORT_PRICE_CENTS", "999"))   # $9.99 default
REPORTS_DIR = pathlib.Path("reports")

from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable, Table, TableStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET", "premier-realty-dev-secret-2024")

AI_MODEL = "claude-sonnet-4-20250514"

# In-memory store for results (keyed by UUID)
results_store: dict = {}

# In-memory chat history store (keyed by session ID)
chat_sessions: dict = {}

ALEX_SYSTEM = """You are Alex, a friendly and knowledgeable real estate assistant for Stephen Wahlquist AI Consulting. You help buyers, sellers, renters, and investors with real estate questions.

Your personality: warm, professional, genuinely helpful — like a trusted friend who happens to be a top real estate agent. Never robotic or salesy.

Your job:
1. Answer questions about buying, selling, renting, and investing in real estate clearly and helpfully.
2. Ask qualifying questions naturally to understand what the visitor needs:
   - What are they looking for? (buy/sell/rent/invest)
   - What's their timeline?
   - What's their budget or price range?
   - What locations or neighborhoods interest them?
   - Are they pre-approved for a mortgage (if buying)?
3. When someone seems ready to take the next step, offer to schedule a consultation. Collect their name, email, phone number, and preferred time — one question at a time, naturally in conversation. When you have all four, confirm the appointment and tell them the team will reach out to confirm.
4. If you collect appointment info (name, email, phone, preferred time), include this EXACTLY at the end of your message so it can be saved:
   APPOINTMENT_DATA:{"name":"...","email":"...","phone":"...","time":"..."}
5. Never give specific legal or financial advice. If asked, say something like "That's a great question for a licensed attorney / financial advisor — I'd recommend consulting one. What I can tell you generally is..."
6. Keep responses concise — 2 to 4 short paragraphs max. Use a friendly, conversational tone.
7. Remember everything from earlier in the conversation and refer back to it naturally."""


# ── Zillow / RapidAPI helpers ────────────────────────────────────────────────────

def _haversine_miles(lat1, lon1, lat2, lon2):
    R = 3958.8
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    a = (math.sin((phi2 - phi1) / 2) ** 2
         + math.cos(phi1) * math.cos(phi2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2)
    return 2 * R * math.asin(math.sqrt(a))


def _geocode(address: str):
    """Return (lat, lon) for an address via free Nominatim API, or (None, None)."""
    try:
        r = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": address, "format": "json", "limit": 1},
            headers={"User-Agent": "SW-AI-Consulting/1.0 (property-valuation-app)"},
            timeout=6,
        )
        data = r.json()
        if data:
            return float(data[0]["lat"]), float(data[0]["lon"])
    except Exception:
        pass
    return None, None


def _extract_location(address: str) -> str:
    """Pull a zip code or 'City, ST' from a full address for the Zillow search."""
    m = re.search(r"\b(\d{5})\b", address)
    if m:
        return m.group(1)
    m = re.search(r"([A-Za-z\s]+),\s*([A-Z]{2})", address)
    if m:
        return f"{m.group(1).strip()}, {m.group(2)}"
    return address


def _fetch_zillow_sold(location: str, beds: str, sqft: str) -> list[dict]:
    """
    Call Zillow56 on RapidAPI for recently sold homes.
    Returns a list of raw result dicts (may be empty).
    Raises on HTTP error.
    """
    if not RAPIDAPI_KEY:
        return []

    params: dict = {
        "location": location,
        "status": "sold",
        "sortSelection": "days",
        "listing_type": "by_agent,by_owner",
    }
    # Soft bed filter — ±1 bed
    if beds:
        try:
            b = int(beds)
            params["bedsMin"] = max(1, b - 1)
            params["bedsMax"] = b + 1
        except ValueError:
            pass

    r = requests.get(
        "https://zillow56.p.rapidapi.com/search",
        headers={
            "X-RapidAPI-Key": RAPIDAPI_KEY,
            "X-RapidAPI-Host": "zillow56.p.rapidapi.com",
        },
        params=params,
        timeout=12,
    )
    r.raise_for_status()
    return r.json().get("results", [])


def _format_zillow_comps(raw_results: list[dict], subject_lat, subject_lon,
                         subject_sqft: str) -> list[dict]:
    """Convert Zillow API rows into the comp card format. Returns up to 6."""
    comps = []
    sqft_num = None
    if subject_sqft:
        try:
            sqft_num = int(subject_sqft.replace(",", ""))
        except ValueError:
            pass

    for r in raw_results:
        street  = r.get("streetAddress") or r.get("address", "")
        city    = r.get("city", "")
        state   = r.get("state", "")
        zipcode = r.get("zipcode", "")
        if not street:
            continue

        full_addr = f"{street}, {city}, {state} {zipcode}".strip(", ")
        price     = r.get("soldPrice") or r.get("price") or 0
        beds      = r.get("bedrooms", "")
        baths     = r.get("bathrooms", "")
        living    = r.get("livingArea", "")
        year      = r.get("yearBuilt", "")
        lat       = r.get("latitude")
        lon       = r.get("longitude")

        if not price:
            continue

        # Build specs string
        specs_parts = []
        if beds:   specs_parts.append(f"{beds} bed")
        if baths:  specs_parts.append(f"{baths} bath")
        if living: specs_parts.append(f"{int(living):,} sq ft")
        if year:   specs_parts.append(f"Built {year}")
        specs = " / ".join(specs_parts) if specs_parts else "Details N/A"

        # Distance
        distance = "—"
        if lat and lon and subject_lat and subject_lon:
            try:
                miles = _haversine_miles(subject_lat, subject_lon, float(lat), float(lon))
                distance = f"{miles:.1f} miles away"
            except Exception:
                pass

        # Date sold (field varies by API version)
        date_sold = (r.get("dateSoldString") or r.get("dateSold") or
                     r.get("sold_date") or "Recent")
        if date_sold and len(date_sold) >= 7:
            try:
                from datetime import datetime as dt
                d = dt.strptime(date_sold[:10], "%Y-%m-%d")
                date_sold = d.strftime("%B %Y")
            except Exception:
                pass

        comps.append({
            "address":  full_addr,
            "specs":    specs,
            "price":    f"${int(price):,}",
            "date":     date_sold,
            "distance": distance,
            "living_area": int(living) if living else None,
        })

        if len(comps) >= 6:
            break

    return comps


def _add_claude_notes(comps: list[dict], subject_address: str,
                      subject_beds: str, subject_baths: str,
                      subject_sqft: str, subject_year: str) -> list[dict]:
    """Ask Claude to add a one-sentence comparison note to each real comp."""
    if not comps:
        return comps

    lines = []
    for i, c in enumerate(comps, 1):
        lines.append(
            f"Comp {i}: {c['address']} | {c['specs']} | Sold {c['price']} in {c['date']}"
        )

    prompt = f"""You are a real estate appraiser. The subject property is:
{subject_address} — {subject_beds} bed / {subject_baths} bath / {subject_sqft} sq ft / Built {subject_year}

Below are REAL recently sold comparable properties. For each comp, write ONE concise sentence (max 20 words) explaining the most important similarity or difference vs the subject that affects the price comparison. Be specific about condition, size, age, or features — not generic.

{chr(10).join(lines)}

Reply ONLY with lines in this exact format:
COMP_1_NOTE: [sentence]
COMP_2_NOTE: [sentence]
... (through COMP_{len(comps)}_NOTE)"""

    try:
        client = anthropic.Anthropic()
        resp = client.messages.create(
            model=AI_MODEL, max_tokens=400,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = resp.content[0].text.strip()
        for i, comp in enumerate(comps, 1):
            marker = f"COMP_{i}_NOTE:"
            pos = raw.find(marker)
            if pos != -1:
                note = raw[pos + len(marker):].split("\n")[0].strip()
                comp["notes"] = note
    except Exception:
        pass  # notes are optional — real data still shown

    return comps


# ── Claude integration ──────────────────────────────────────────────────────────

def call_claude(prop: dict, comps: list[dict]) -> dict:
    comps_text = "\n".join(
        f"  Comp {i+1}: {c['address']} — sold for {c['price']}"
        for i, c in enumerate(comps) if c.get("address") and c.get("price")
    )

    prompt = f"""You are a licensed real estate appraiser and market analyst. Analyze this property and provide a professional valuation.

SUBJECT PROPERTY:
  Address:    {prop['address']}
  Bedrooms:   {prop['beds']}
  Bathrooms:  {prop['baths']}
  Sq Footage: {prop['sqft']} sq ft
  Lot Size:   {prop['lot']}
  Year Built: {prop['year_built']}
  Condition:  {prop['condition']}

RECENT NEIGHBORHOOD COMPS:
{comps_text}

Provide your analysis using EXACTLY these section markers (I parse them programmatically):

ESTIMATED_VALUE:
[A specific dollar range, e.g. "$415,000 – $435,000". Be realistic based on the comps provided.]

METHODOLOGY:
[2–3 sentences explaining how you arrived at this range. Reference the comps specifically. Mention price-per-sqft adjustments for condition and features. Professional appraiser tone.]

MARKET_CONTEXT:
[2–3 sentences of market context. What do these comps suggest about the local market? Is inventory tight or loose? Are prices trending up or flat? Sound like a knowledgeable local expert.]

RECOMMENDATION_1_TITLE:
[Short title, 5 words max]
RECOMMENDATION_1_BODY:
[2–3 sentences. Specific, actionable advice for maximizing sale price. Reference the property details.]

RECOMMENDATION_2_TITLE:
[Short title, 5 words max]
RECOMMENDATION_2_BODY:
[2–3 sentences. Different angle from Recommendation 1.]

RECOMMENDATION_3_TITLE:
[Short title, 5 words max]
RECOMMENDATION_3_BODY:
[2–3 sentences. Different angle from the first two.]

Rules:
- Use real numbers from the comps
- Be specific, not generic
- Professional but readable — not overly technical
- No markdown, no asterisks, plain prose in body sections"""

    client = anthropic.Anthropic()
    response = client.messages.create(
        model=AI_MODEL,
        max_tokens=1200,
        messages=[{"role": "user", "content": prompt}],
    )
    return parse_claude(response.content[0].text.strip())


def parse_claude(text: str) -> dict:
    keys = [
        "ESTIMATED_VALUE", "METHODOLOGY", "MARKET_CONTEXT",
        "RECOMMENDATION_1_TITLE", "RECOMMENDATION_1_BODY",
        "RECOMMENDATION_2_TITLE", "RECOMMENDATION_2_BODY",
        "RECOMMENDATION_3_TITLE", "RECOMMENDATION_3_BODY",
    ]
    result = {}
    for i, key in enumerate(keys):
        marker = f"{key}:"
        start = text.find(marker)
        if start == -1:
            result[key] = ""
            continue
        start += len(marker)
        end = len(text)
        for next_key in keys[i + 1:]:
            pos = text.find(f"{next_key}:", start)
            if pos != -1:
                end = pos
                break
        result[key] = text[start:end].strip()
    return result


# ── PDF generation ──────────────────────────────────────────────────────────────

NAVY  = colors.HexColor("#1a2332")
GOLD  = colors.HexColor("#c8a97e")
LGRAY = colors.HexColor("#f5f6f8")
DGRAY = colors.HexColor("#4a5568")
WHITE = colors.white


def build_pdf(prop: dict, comps: list[dict], analysis: dict) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=letter,
        leftMargin=0.85 * inch,
        rightMargin=0.85 * inch,
        topMargin=0.85 * inch,
        bottomMargin=0.85 * inch,
    )

    styles = getSampleStyleSheet()

    def style(name, **kw):
        return ParagraphStyle(name, **kw)

    s_title   = style("Title2",   fontSize=22, textColor=WHITE,  fontName="Helvetica-Bold", alignment=TA_CENTER, spaceAfter=4)
    s_sub     = style("Sub",      fontSize=11, textColor=GOLD,   fontName="Helvetica",      alignment=TA_CENTER, spaceAfter=2)
    s_label   = style("Label",    fontSize=8,  textColor=GOLD,   fontName="Helvetica-Bold", spaceBefore=14, spaceAfter=3, leading=12)
    s_value   = style("Value",    fontSize=22, textColor=NAVY,   fontName="Helvetica-Bold", alignment=TA_CENTER, spaceAfter=6)
    s_section = style("Section",  fontSize=11, textColor=NAVY,   fontName="Helvetica-Bold", spaceBefore=18, spaceAfter=6)
    s_body    = style("Body2",    fontSize=10, textColor=DGRAY,  fontName="Helvetica",      leading=16, spaceAfter=6)
    s_rec_ttl = style("RecTitle", fontSize=10, textColor=NAVY,   fontName="Helvetica-Bold", spaceBefore=10, spaceAfter=3)
    s_small   = style("Small",    fontSize=8,  textColor=DGRAY,  fontName="Helvetica",      alignment=TA_RIGHT)

    story = []

    # Header banner (fake it with a table)
    header_data = [[
        Paragraph("STEPHEN WAHLQUIST AI CONSULTING", s_title),
    ]]
    header_tbl = Table(header_data, colWidths=[6.3 * inch])
    header_tbl.setStyle(TableStyle([
        ("BACKGROUND",  (0, 0), (-1, -1), NAVY),
        ("TOPPADDING",  (0, 0), (-1, -1), 20),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
        ("LEFTPADDING",  (0, 0), (-1, -1), 16),
        ("RIGHTPADDING", (0, 0), (-1, -1), 16),
        ("ROUNDEDCORNERS", [6]),
    ]))
    story.append(header_tbl)
    story.append(Spacer(1, 6))

    sub_data = [[Paragraph("AI Property Valuation Report", s_sub)]]
    sub_tbl = Table(sub_data, colWidths=[6.3 * inch])
    sub_tbl.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), colors.HexColor("#2c3e55")),
        ("TOPPADDING",    (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(sub_tbl)
    story.append(Spacer(1, 14))

    # Property details table
    story.append(Paragraph("SUBJECT PROPERTY", s_label))
    story.append(HRFlowable(width="100%", thickness=2, color=GOLD, spaceAfter=8))

    detail_rows = [
        ["Address", prop["address"]],
        ["Beds / Baths", f"{prop['beds']} bed  /  {prop['baths']} bath"],
        ["Square Footage", f"{prop['sqft']} sq ft"],
        ["Lot Size", prop["lot"]],
        ["Year Built", prop["year_built"]],
        ["Condition", prop["condition"]],
    ]
    det_tbl = Table(detail_rows, colWidths=[1.6 * inch, 4.7 * inch])
    det_tbl.setStyle(TableStyle([
        ("FONTNAME",     (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME",     (1, 0), (1, -1), "Helvetica"),
        ("FONTSIZE",     (0, 0), (-1, -1), 9),
        ("TEXTCOLOR",    (0, 0), (0, -1), NAVY),
        ("TEXTCOLOR",    (1, 0), (1, -1), DGRAY),
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [WHITE, LGRAY]),
        ("TOPPADDING",   (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 6),
        ("LEFTPADDING",  (0, 0), (-1, -1), 8),
    ]))
    story.append(det_tbl)
    story.append(Spacer(1, 16))

    # Comps
    valid_comps = [c for c in comps if c.get("address") and c.get("price")]
    if valid_comps:
        story.append(Paragraph("COMPARABLE SALES", s_label))
        story.append(HRFlowable(width="100%", thickness=2, color=GOLD, spaceAfter=8))
        comp_rows = [["#", "Address", "Sale Price"]]
        for i, c in enumerate(valid_comps, 1):
            comp_rows.append([str(i), c["address"], c["price"]])
        comp_tbl = Table(comp_rows, colWidths=[0.3 * inch, 4.5 * inch, 1.5 * inch])
        comp_tbl.setStyle(TableStyle([
            ("BACKGROUND",   (0, 0), (-1, 0), NAVY),
            ("TEXTCOLOR",    (0, 0), (-1, 0), WHITE),
            ("FONTNAME",     (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTNAME",     (0, 1), (-1, -1), "Helvetica"),
            ("FONTSIZE",     (0, 0), (-1, -1), 9),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, LGRAY]),
            ("TOPPADDING",   (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING",(0, 0), (-1, -1), 6),
            ("LEFTPADDING",  (0, 0), (-1, -1), 8),
            ("TEXTCOLOR",    (0, 1), (-1, -1), DGRAY),
            ("TEXTCOLOR",    (0, 1), (0, -1), NAVY),
        ]))
        story.append(comp_tbl)
        story.append(Spacer(1, 16))

    # Estimated value — hero box
    story.append(Paragraph("ESTIMATED VALUE RANGE", s_label))
    story.append(HRFlowable(width="100%", thickness=2, color=GOLD, spaceAfter=8))
    val_data = [[Paragraph(analysis.get("ESTIMATED_VALUE", "—"), s_value)]]
    val_tbl = Table(val_data, colWidths=[6.3 * inch])
    val_tbl.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), LGRAY),
        ("TOPPADDING",    (0, 0), (-1, -1), 18),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 18),
        ("ROUNDEDCORNERS", [6]),
    ]))
    story.append(val_tbl)
    story.append(Spacer(1, 16))

    # Methodology
    story.append(Paragraph("VALUATION METHODOLOGY", s_section))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#e2e8f0"), spaceAfter=6))
    story.append(Paragraph(analysis.get("METHODOLOGY", ""), s_body))

    # Market context
    story.append(Paragraph("MARKET CONTEXT", s_section))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#e2e8f0"), spaceAfter=6))
    story.append(Paragraph(analysis.get("MARKET_CONTEXT", ""), s_body))

    # Recommendations
    story.append(Paragraph("RECOMMENDATIONS TO MAXIMIZE SALE PRICE", s_section))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#e2e8f0"), spaceAfter=6))

    for n in ("1", "2", "3"):
        title = analysis.get(f"RECOMMENDATION_{n}_TITLE", "")
        body  = analysis.get(f"RECOMMENDATION_{n}_BODY", "")
        if title or body:
            rec_data = [[
                Paragraph(f"{n}", ParagraphStyle("Num", fontSize=14, textColor=WHITE, fontName="Helvetica-Bold", alignment=TA_CENTER)),
                Paragraph(f"<b>{title}</b><br/>{body}", ParagraphStyle("RecBody", fontSize=9, textColor=DGRAY, fontName="Helvetica", leading=15)),
            ]]
            rec_tbl = Table(rec_data, colWidths=[0.4 * inch, 5.9 * inch])
            rec_tbl.setStyle(TableStyle([
                ("BACKGROUND",    (0, 0), (0, 0), GOLD),
                ("BACKGROUND",    (1, 0), (1, 0), LGRAY),
                ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING",    (0, 0), (-1, -1), 12),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
                ("LEFTPADDING",   (1, 0), (1, 0), 14),
                ("ROUNDEDCORNERS", [4]),
            ]))
            story.append(rec_tbl)
            story.append(Spacer(1, 8))

    # Footer
    story.append(Spacer(1, 20))
    story.append(HRFlowable(width="100%", thickness=1, color=GOLD))
    story.append(Spacer(1, 6))
    generated = datetime.now().strftime("%B %d, %Y at %I:%M %p")
    story.append(Paragraph(
        f"Generated by Stephen Wahlquist AI Consulting  ·  {generated}  ·  For informational purposes only.",
        s_small
    ))

    doc.build(story)
    buf.seek(0)
    return buf.read()


# ── Routes ──────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/analyze", methods=["POST"])
def analyze():
    prop = {
        "address":    request.form.get("address", "").strip(),
        "beds":       request.form.get("beds", "").strip(),
        "baths":      request.form.get("baths", "").strip(),
        "sqft":       request.form.get("sqft", "").strip(),
        "lot":        request.form.get("lot", "").strip(),
        "year_built": request.form.get("year_built", "").strip(),
        "condition":  request.form.get("condition", "Good"),
    }

    comps = []
    for i in range(1, 4):
        comps.append({
            "address": request.form.get(f"comp{i}_address", "").strip(),
            "price":   request.form.get(f"comp{i}_price", "").strip(),
        })

    # Basic validation
    if not prop["address"] or not prop["sqft"]:
        flash("Please fill in at least the property address and square footage.", "error")
        return redirect(url_for("index"))

    try:
        analysis = call_claude(prop, comps)
    except anthropic.AuthenticationError:
        flash("API key error. Please set your ANTHROPIC_API_KEY environment variable.", "error")
        return redirect(url_for("index"))
    except Exception as e:
        flash(f"Something went wrong generating the analysis: {str(e)}", "error")
        return redirect(url_for("index"))

    result_id  = str(uuid.uuid4())
    result_data = {
        "prop":      prop,
        "comps":     comps,
        "analysis":  analysis,
        "generated": datetime.now().strftime("%B %d, %Y"),
        "paid":      False,
    }
    results_store[result_id] = result_data

    # Persist to disk so it survives the Stripe redirect
    REPORTS_DIR.mkdir(exist_ok=True)
    (REPORTS_DIR / f"{result_id}.json").write_text(
        json.dumps(result_data, default=str), encoding="utf-8"
    )

    return redirect(url_for("results", result_id=result_id))


def load_result(result_id):
    """Load result from memory or disk."""
    if result_id in results_store:
        return results_store[result_id]
    path = REPORTS_DIR / f"{result_id}.json"
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        results_store[result_id] = data
        return data
    return None


@app.route("/results/<result_id>")
def results(result_id):
    data = load_result(result_id)
    if not data:
        flash("Report not found or expired. Please submit a new valuation.", "error")
        return redirect(url_for("index"))
    return render_template("results.html", result_id=result_id,
                           price=f"${REPORT_PRICE_CENTS/100:.2f}", **data)


@app.route("/download/<result_id>")
def download(result_id):
    data = load_result(result_id)
    if not data:
        flash("Report not found.", "error")
        return redirect(url_for("index"))

    # Must be paid
    if not data.get("paid"):
        flash("Please complete payment to download your report.", "error")
        return redirect(url_for("results", result_id=result_id))

    pdf_bytes = build_pdf(data["prop"], data["comps"], data["analysis"])
    address_slug = data["prop"]["address"].replace(" ", "_").replace(",", "")[:40]
    filename = f"Valuation_{address_slug}.pdf"

    return send_file(
        io.BytesIO(pdf_bytes),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=filename,
    )


@app.route("/create-checkout-session/<result_id>", methods=["POST"])
def create_checkout_session(result_id):
    data = load_result(result_id)
    if not data:
        flash("Report not found.", "error")
        return redirect(url_for("index"))

    if not stripe.api_key:
        flash("Payment system not configured. Contact the site administrator.", "error")
        return redirect(url_for("results", result_id=result_id))

    address = data["prop"]["address"]
    base_url = request.host_url.rstrip("/")

    try:
        checkout = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{
                "price_data": {
                    "currency": "usd",
                    "unit_amount": REPORT_PRICE_CENTS,
                    "product_data": {
                        "name": "AI Property Valuation Report",
                        "description": f"Full branded PDF report — {address}",
                        "images": [],
                    },
                },
                "quantity": 1,
            }],
            mode="payment",
            success_url=(
                f"{base_url}/payment-success"
                f"?session_id={{CHECKOUT_SESSION_ID}}&result_id={result_id}"
            ),
            cancel_url=f"{base_url}/results/{result_id}",
            metadata={"result_id": result_id},
        )
        return redirect(checkout.url, code=303)

    except stripe.error.StripeError as e:
        flash(f"Payment error: {e.user_message or str(e)}", "error")
        return redirect(url_for("results", result_id=result_id))


@app.route("/payment-success")
def payment_success():
    session_id = request.args.get("session_id", "")
    result_id  = request.args.get("result_id", "")

    if not session_id or not result_id:
        flash("Invalid payment confirmation.", "error")
        return redirect(url_for("index"))

    data = load_result(result_id)
    if not data:
        flash("Report not found.", "error")
        return redirect(url_for("index"))

    # Verify payment with Stripe
    try:
        checkout = stripe.checkout.Session.retrieve(session_id)
        if checkout.payment_status == "paid":
            data["paid"] = True
            results_store[result_id] = data
            # Update persisted file
            path = REPORTS_DIR / f"{result_id}.json"
            if path.exists():
                path.write_text(json.dumps(data, default=str), encoding="utf-8")
        else:
            flash("Payment not confirmed. Please try again.", "error")
            return redirect(url_for("results", result_id=result_id))
    except stripe.error.StripeError as e:
        flash(f"Could not verify payment: {str(e)}", "error")
        return redirect(url_for("results", result_id=result_id))

    return render_template("payment_success.html", result_id=result_id,
                           address=data["prop"]["address"])


@app.route("/payment-cancel/<result_id>")
def payment_cancel(result_id):
    flash("Payment cancelled. Your report is still available if you'd like to try again.", "error")
    return redirect(url_for("results", result_id=result_id))


@app.route("/calculator")
def calculator():
    embed = request.args.get("embed", "false").lower() in ("1", "true", "yes")
    return render_template("calculator.html", embed=embed)


@app.route("/calculator-chat", methods=["POST"])
def calculator_chat():
    data        = request.get_json()
    income      = data.get("income", "")
    extra       = data.get("message", "")
    history     = data.get("history", [])

    if not income and not extra:
        return jsonify({"error": "No input provided"}), 400

    system = """You are Alex, a friendly real estate advisor at Premier Realty. The user is using a mortgage calculator and wants to know what home price they can comfortably afford.

When given a monthly income figure:
1. Use the standard guideline that housing costs should be 28% or less of gross monthly income (the "28% rule")
2. Also mention the 36% total-debt rule as a reality check
3. Account for property taxes (~1.2% of home value/year), insurance (~0.5%/year), and assume ~20% down payment at ~6.5-7% interest unless they tell you otherwise
4. Give a specific comfortable price range (e.g. "$320,000–$380,000") with a brief explanation
5. Mention one or two factors that could adjust this up or down (credit score, existing debts, location)
6. Keep it to 3–4 short paragraphs. Be warm and encouraging, not clinical.
7. End with a question — ask if they want to talk to one of our agents for a full pre-approval estimate.

Never give tax or legal advice. If they ask something outside home affordability, gently redirect."""

    messages = history.copy()
    user_msg = f"My gross monthly income is ${income}." if income and not history else extra
    messages.append({"role": "user", "content": user_msg})

    try:
        client   = anthropic.Anthropic()
        response = client.messages.create(
            model=AI_MODEL,
            max_tokens=600,
            system=system,
            messages=messages,
        )
        reply = response.content[0].text.strip()
        messages.append({"role": "assistant", "content": reply})
        return jsonify({"reply": reply, "history": messages})
    except anthropic.AuthenticationError:
        return jsonify({"error": "API key missing. Set ANTHROPIC_API_KEY."}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/neighborhood")
def neighborhood():
    return render_template("neighborhood.html")


def _neighborhood_prompt(name: str, city: str) -> str:
    return f"""You are a knowledgeable real estate market analyst. Generate a comprehensive neighborhood profile for: {name}, {city}.

Use EXACTLY these section markers (parsed programmatically — do not deviate):

TAGLINE:
[One punchy, memorable sentence that captures this neighborhood's essence.]

VIBE:
[3–4 sentences. Overall character, atmosphere, history, and feel. What does it look and feel like to walk around?]

BUYER_PROFILE:
[2–3 sentences. Who typically buys here? Age range, lifestyle, motivations.]

PRICE_TRENDS:
[3–4 sentences. General price direction over recent years, what's driving it, how it compares to the broader city market. Be specific about trends without quoting exact prices.]

PROS_BUYERS:
- [Specific pro for buyers, one line]
- [Another pro]
- [Another pro]
- [Another pro]
- [Another pro]

CONS_BUYERS:
- [Specific con for buyers, one line]
- [Another con]
- [Another con]
- [Another con]

PROS_SELLERS:
- [Specific pro for sellers, one line]
- [Another pro]
- [Another pro]
- [Another pro]

CONS_SELLERS:
- [Specific con for sellers, one line]
- [Another con]
- [Another con]
- [Another con]

RENTAL_YIELD:
[2–3 sentences. Typical gross rental yield range (e.g. "3–5%"), what types of rentals perform best, and what drives rental demand here.]

SCHOOLS:
[2–3 sentences. General school quality, whether public schools are a draw or a concern, proximity to good schools, any notable institutions.]

WALKABILITY:
[2–3 sentences. Walk score context, transit options (subway, bus, bike lanes), car dependency, parking situation.]

BEST_FOR:
FAMILIES: [Strong Fit / Good Fit / Moderate Fit / Poor Fit] | [One sentence explanation]
YOUNG_PROFESSIONALS: [Strong Fit / Good Fit / Moderate Fit / Poor Fit] | [One sentence explanation]
RETIREES: [Strong Fit / Good Fit / Moderate Fit / Poor Fit] | [One sentence explanation]
INVESTORS: [Strong Fit / Good Fit / Moderate Fit / Poor Fit] | [One sentence explanation]

Rules:
- Be specific and honest — don't be purely promotional
- If the neighborhood has real downsides, name them clearly
- Base your response on well-known characteristics of this area
- No markdown formatting, no asterisks, plain text in all body sections
- Each bullet point must start with "- " (dash space)"""


def _parse_neighborhood(text: str) -> dict:
    keys = [
        "TAGLINE", "VIBE", "BUYER_PROFILE", "PRICE_TRENDS",
        "PROS_BUYERS", "CONS_BUYERS", "PROS_SELLERS", "CONS_SELLERS",
        "RENTAL_YIELD", "SCHOOLS", "WALKABILITY", "BEST_FOR",
    ]
    result = {}
    for i, key in enumerate(keys):
        marker = f"{key}:"
        start  = text.find(marker)
        if start == -1:
            result[key] = ""
            continue
        start += len(marker)
        end = len(text)
        for nk in keys[i + 1:]:
            pos = text.find(f"{nk}:", start)
            if pos != -1:
                end = pos
                break
        raw = text[start:end].strip()
        # Parse bullet lists into arrays
        if key in ("PROS_BUYERS", "CONS_BUYERS", "PROS_SELLERS", "CONS_SELLERS"):
            result[key] = [ln.lstrip("- ").strip() for ln in raw.splitlines() if ln.strip().startswith("-")]
        elif key == "BEST_FOR":
            best = {}
            for line in raw.splitlines():
                if "|" in line:
                    label, rest = line.split("|", 1)
                    label = label.strip().rstrip(":")
                    fit, *note = rest.strip().split(" ", 1)
                    best[label] = {"fit": fit.strip(), "note": note[0].strip() if note else ""}
            result[key] = best
        else:
            result[key] = raw
    return result


@app.route("/neighborhood/analyze", methods=["POST"])
def neighborhood_analyze():
    data = request.get_json()
    name = (data.get("name") or "").strip()
    city = (data.get("city") or "").strip()
    if not name or not city:
        return jsonify({"error": "Neighborhood name and city are required."}), 400
    try:
        client   = anthropic.Anthropic()
        response = client.messages.create(
            model=AI_MODEL,
            max_tokens=1600,
            messages=[{"role": "user", "content": _neighborhood_prompt(name, city)}],
        )
        parsed = _parse_neighborhood(response.content[0].text.strip())
        return jsonify({"ok": True, "name": name, "city": city, "profile": parsed})
    except anthropic.AuthenticationError:
        return jsonify({"error": "API key missing. Set ANTHROPIC_API_KEY."}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/neighborhood/compare", methods=["POST"])
def neighborhood_compare():
    data  = request.get_json()
    n1, c1 = (data.get("name1") or "").strip(), (data.get("city1") or "").strip()
    n2, c2 = (data.get("name2") or "").strip(), (data.get("city2") or "").strip()
    if not n1 or not c1 or not n2 or not c2:
        return jsonify({"error": "Both neighborhoods and cities are required."}), 400

    compare_prompt = f"""You are a real estate market analyst. Compare these two neighborhoods side by side:
Neighborhood A: {n1}, {c1}
Neighborhood B: {n2}, {c2}

First provide a full profile for each using the markers below, then a comparison verdict.

=== NEIGHBORHOOD_A ===
{_neighborhood_prompt(n1, c1).split("Rules:")[0]}

=== NEIGHBORHOOD_B ===
{_neighborhood_prompt(n2, c2).split("Rules:")[0]}

=== COMPARISON ===
WINNER_BUYERS:
[Either "{n1}" or "{n2}" or "Tie"] | [2 sentences explaining which is better for buyers and why]

WINNER_SELLERS:
[Either "{n1}" or "{n2}" or "Tie"] | [2 sentences explaining which is better for sellers and why]

WINNER_INVESTORS:
[Either "{n1}" or "{n2}" or "Tie"] | [2 sentences explaining which has better investment fundamentals]

KEY_DIFFERENCES:
- [Most important difference between the two, one line]
- [Second key difference]
- [Third key difference]
- [Fourth key difference]

Rules: Be specific and honest. No markdown. Bullets start with "- ". Pipe "|" separates label from explanation in WINNER fields."""

    try:
        client   = anthropic.Anthropic()
        response = client.messages.create(
            model=AI_MODEL,
            max_tokens=3200,
            messages=[{"role": "user", "content": compare_prompt}],
        )
        raw = response.content[0].text.strip()

        # Split into sections
        a_start = raw.find("=== NEIGHBORHOOD_A ===")
        b_start = raw.find("=== NEIGHBORHOOD_B ===")
        c_start = raw.find("=== COMPARISON ===")

        raw_a = raw[a_start + len("=== NEIGHBORHOOD_A ==="):b_start].strip() if a_start != -1 and b_start != -1 else ""
        raw_b = raw[b_start + len("=== NEIGHBORHOOD_B ==="):c_start].strip() if b_start != -1 and c_start != -1 else ""
        raw_c = raw[c_start + len("=== COMPARISON ==="):].strip() if c_start != -1 else ""

        profile_a = _parse_neighborhood(raw_a)
        profile_b = _parse_neighborhood(raw_b)

        # Parse comparison block
        comparison = {}
        for key in ("WINNER_BUYERS", "WINNER_SELLERS", "WINNER_INVESTORS"):
            marker = f"{key}:"
            pos = raw_c.find(marker)
            if pos != -1:
                line = raw_c[pos + len(marker):].split("\n")[0].strip()
                if "|" in line:
                    winner, note = line.split("|", 1)
                    comparison[key] = {"winner": winner.strip(), "note": note.strip()}
                else:
                    comparison[key] = {"winner": line, "note": ""}

        diffs_start = raw_c.find("KEY_DIFFERENCES:")
        if diffs_start != -1:
            diffs_raw = raw_c[diffs_start + len("KEY_DIFFERENCES:"):].strip()
            comparison["KEY_DIFFERENCES"] = [
                ln.lstrip("- ").strip() for ln in diffs_raw.splitlines() if ln.strip().startswith("-")
            ]

        return jsonify({
            "ok": True,
            "a": {"name": n1, "city": c1, "profile": profile_a},
            "b": {"name": n2, "city": c2, "profile": profile_b},
            "comparison": comparison,
        })
    except anthropic.AuthenticationError:
        return jsonify({"error": "API key missing. Set ANTHROPIC_API_KEY."}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/chat")
def chat():
    return render_template("chat.html")


@app.route("/api/chat", methods=["POST"])
def api_chat():
    data       = request.get_json()
    message    = (data.get("message") or "").strip()
    session_id = data.get("session_id") or str(uuid.uuid4())

    if not message:
        return jsonify({"error": "No message provided"}), 400

    # Load or init conversation history
    history = chat_sessions.get(session_id, [])
    history.append({"role": "user", "content": message})

    try:
        client   = anthropic.Anthropic()
        response = client.messages.create(
            model=AI_MODEL,
            max_tokens=600,
            system=ALEX_SYSTEM,
            messages=history,
        )
        reply = response.content[0].text.strip()

        # Check for appointment data and save it
        appt_marker = "APPOINTMENT_DATA:"
        clean_reply  = reply
        if appt_marker in reply:
            try:
                marker_pos = reply.find(appt_marker)
                json_str   = reply[marker_pos + len(appt_marker):].strip()
                # Find the JSON object
                end_pos = json_str.find("}") + 1
                appt    = json.loads(json_str[:end_pos])
                # Save to file
                with open("appointment_requests.txt", "a", encoding="utf-8") as f:
                    f.write(f"\n{'='*50}\n")
                    f.write(f"Date: {datetime.now().strftime('%B %d, %Y at %I:%M %p')}\n")
                    f.write(f"Name:  {appt.get('name','')}\n")
                    f.write(f"Email: {appt.get('email','')}\n")
                    f.write(f"Phone: {appt.get('phone','')}\n")
                    f.write(f"Preferred Time: {appt.get('time','')}\n")
                # Strip the data marker from the displayed reply
                clean_reply = reply[:marker_pos].strip()
            except Exception:
                clean_reply = reply.replace(appt_marker, "").strip()

        history.append({"role": "assistant", "content": reply})
        chat_sessions[session_id] = history[-20:]  # Keep last 20 messages

        return jsonify({
            "reply":      clean_reply,
            "session_id": session_id,
        })

    except anthropic.AuthenticationError:
        return jsonify({"error": "API key missing. Set ANTHROPIC_API_KEY."}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/leads")
def leads():
    return render_template("leads.html")


@app.route("/leads/generate", methods=["POST"])
def leads_generate():
    data         = request.get_json()
    name         = (data.get("name") or "").strip()
    status       = (data.get("status") or "New").strip()
    budget       = (data.get("budget") or "").strip()
    neighborhoods = (data.get("neighborhoods") or "").strip()
    prop_type    = (data.get("prop_type") or "Buy").strip()
    notes        = (data.get("notes") or "").strip()
    output_type  = (data.get("output_type") or "email").strip().lower()  # "email" or "sms"

    if not name:
        return jsonify({"error": "Client name is required."}), 400

    status_guidance = {
        "Hot": (
            "This lead is HOT — they are ready to move NOW. Be urgent and direct. "
            "Suggest a specific showing this week, mention that good inventory moves fast, "
            "and include a clear call-to-action to book a showing or call today. "
            "Tone: energetic, excited, helpful urgency — not pushy."
        ),
        "Warm": (
            "This lead is WARM — interested but not moving fast. Give them a friendly, "
            "no-pressure check-in. Mention that a few new listings just hit the market "
            "that match their criteria, and offer to send them over. "
            "Tone: warm, helpful, low-pressure, conversational."
        ),
        "Cold": (
            "This lead has gone COLD — it's been a while. Re-engage with a light touch. "
            "Lead with a local market update or interesting insight as a value hook. "
            "Don't reference how long it's been. End with a soft, optional CTA. "
            "Tone: relaxed, informative, zero pressure."
        ),
        "New": (
            "This is a BRAND NEW lead — first contact. Make a warm, welcoming first impression. "
            "Introduce yourself, acknowledge what they're looking for, and offer immediate value "
            "(a free valuation, a market snapshot, a personalized search). "
            "Tone: friendly, professional, excited to help."
        ),
        "Closed": (
            "This client has already CLOSED — maintain the relationship. Check in warmly, "
            "reference how things are going with the property, mention you're always available "
            "for referrals or future needs. Maybe share a useful homeowner tip or local update. "
            "Tone: warm, personal, relationship-focused — not transactional."
        ),
    }.get(status, "Be professional, helpful, and friendly.")

    details_block = f"Client Name: {name}\nLead Status: {status}\n"
    if budget:
        details_block += f"Budget Range: {budget}\n"
    if neighborhoods:
        details_block += f"Desired Neighborhoods: {neighborhoods}\n"
    details_block += f"Property Interest: {prop_type}\n"
    if notes:
        details_block += f"\nNotes from last conversation:\n{notes}\n"

    if output_type == "sms":
        prompt = f"""You are a top real estate agent writing a personalized SMS follow-up to a client.

CLIENT DETAILS:
{details_block}

STATUS GUIDANCE:
{status_guidance}

Write ONE SMS message. Requirements:
- Maximum 160 characters (hard limit — count carefully)
- Must feel personal and reference something specific from the notes if provided
- Natural, human tone — not robotic or template-sounding
- No salesy buzzwords
- End with your name: Stephen

Respond with ONLY this format (no extra commentary):
SMS_MESSAGE:
[the message text]
CHAR_COUNT:
[integer character count of the message only]"""

    else:
        prompt = f"""You are a top real estate agent writing a personalized follow-up email to a client.

CLIENT DETAILS:
{details_block}

STATUS GUIDANCE:
{status_guidance}

Write a follow-up email. Requirements:
- Subject line: punchy, specific, not generic — ideally references something personal or timely
- Body: under 150 words, conversational paragraphs, no bullet lists
- Must feel personal and reference something specific from the notes if provided
- Natural, human tone — like a trusted advisor, not a mass email
- End with your name: Stephen Wahlquist
- No salesy buzzwords or clichés

Respond with ONLY this format (no extra commentary):
SUBJECT:
[subject line text]
BODY:
[email body text]"""

    try:
        client   = anthropic.Anthropic()
        response = client.messages.create(
            model=AI_MODEL,
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()

        if output_type == "sms":
            sms_msg, char_count = "", 0
            msg_start = raw.find("SMS_MESSAGE:")
            cnt_start = raw.find("CHAR_COUNT:")
            if msg_start != -1:
                msg_end  = cnt_start if cnt_start != -1 else len(raw)
                sms_msg  = raw[msg_start + len("SMS_MESSAGE:"):msg_end].strip()
            if cnt_start != -1:
                cnt_raw  = raw[cnt_start + len("CHAR_COUNT:"):].strip().split()[0]
                try:
                    char_count = int(cnt_raw)
                except ValueError:
                    char_count = len(sms_msg)
            if not char_count:
                char_count = len(sms_msg)
            return jsonify({"ok": True, "type": "sms", "message": sms_msg, "char_count": char_count})

        else:
            subject, body = "", ""
            subj_start = raw.find("SUBJECT:")
            body_start = raw.find("BODY:")
            if subj_start != -1:
                subj_end = body_start if body_start != -1 else len(raw)
                subject  = raw[subj_start + len("SUBJECT:"):subj_end].strip()
            if body_start != -1:
                body = raw[body_start + len("BODY:"):].strip()
            return jsonify({"ok": True, "type": "email", "subject": subject, "body": body})

    except anthropic.AuthenticationError:
        return jsonify({"error": "API key missing. Set ANTHROPIC_API_KEY."}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/deals")
def deals():
    return render_template("deals.html")


@app.route("/deals/analyze", methods=["POST"])
def deals_analyze():
    data = request.get_json()

    try:
        purchase_price      = float(data.get("purchase_price", 0) or 0)
        down_pct            = float(data.get("down_pct", 20) or 20)
        annual_rate         = float(data.get("annual_rate", 7.25) or 7.25)
        loan_term_years     = int(data.get("loan_term", 30) or 30)
        monthly_rent        = float(data.get("monthly_rent", 0) or 0)
        vacancy_rate        = float(data.get("vacancy_rate", 5) or 5)
        monthly_tax         = float(data.get("monthly_tax", 0) or 0)
        monthly_insurance   = float(data.get("monthly_insurance", 0) or 0)
        monthly_maintenance = float(data.get("monthly_maintenance", 0) or 0)
        mgmt_pct            = float(data.get("mgmt_pct", 10) or 10)
        monthly_hoa         = float(data.get("monthly_hoa", 0) or 0)
        address             = (data.get("address") or "").strip()
    except (TypeError, ValueError) as e:
        return jsonify({"error": f"Invalid number in form: {e}"}), 400

    if purchase_price <= 0 or monthly_rent <= 0:
        return jsonify({"error": "Purchase price and monthly rent are required."}), 400

    # ── Core calculations ──────────────────────────────────────────────
    down_payment     = purchase_price * (down_pct / 100)
    loan_amount      = purchase_price - down_payment
    monthly_rate     = (annual_rate / 100) / 12
    n                = loan_term_years * 12

    if monthly_rate > 0:
        monthly_mortgage = loan_amount * (monthly_rate * (1 + monthly_rate) ** n) / ((1 + monthly_rate) ** n - 1)
    else:
        monthly_mortgage = loan_amount / n if n > 0 else 0

    gross_monthly_income  = monthly_rent
    vacancy_loss          = gross_monthly_income * (vacancy_rate / 100)
    effective_gross       = gross_monthly_income - vacancy_loss
    management_fee        = monthly_rent * (mgmt_pct / 100)
    monthly_expenses      = monthly_tax + monthly_insurance + monthly_maintenance + management_fee + monthly_hoa
    monthly_noi           = effective_gross - monthly_expenses
    annual_noi            = monthly_noi * 12
    cap_rate              = (annual_noi / purchase_price * 100) if purchase_price > 0 else 0
    monthly_cash_flow     = monthly_noi - monthly_mortgage
    annual_cash_flow      = monthly_cash_flow * 12
    closing_costs         = purchase_price * 0.03
    total_cash_invested   = down_payment + closing_costs
    cash_on_cash          = (annual_cash_flow / total_cash_invested * 100) if total_cash_invested > 0 else 0
    annual_gross_rent     = monthly_rent * 12
    grm                   = (purchase_price / annual_gross_rent) if annual_gross_rent > 0 else 0
    one_pct_rule          = monthly_rent >= (purchase_price * 0.01)
    one_pct_threshold     = purchase_price * 0.01

    # ── Deal score (1–10) ──────────────────────────────────────────────
    score = 1
    if cap_rate > 8:
        score += 2
    elif cap_rate > 6:
        score += 1
    if cash_on_cash > 10:
        score += 2
    elif cash_on_cash > 7:
        score += 1
    if one_pct_rule:
        score += 2
    if grm < 8:
        score += 2
    elif grm < 12:
        score += 1
    if monthly_cash_flow > 0:
        score += 1

    metrics = {
        "address":             address,
        "purchase_price":      purchase_price,
        "down_payment":        down_payment,
        "down_pct":            down_pct,
        "loan_amount":         loan_amount,
        "annual_rate":         annual_rate,
        "loan_term_years":     loan_term_years,
        "monthly_mortgage":    monthly_mortgage,
        "monthly_rent":        monthly_rent,
        "vacancy_rate":        vacancy_rate,
        "vacancy_loss":        vacancy_loss,
        "effective_gross":     effective_gross,
        "management_fee":      management_fee,
        "monthly_tax":         monthly_tax,
        "monthly_insurance":   monthly_insurance,
        "monthly_maintenance": monthly_maintenance,
        "monthly_hoa":         monthly_hoa,
        "monthly_expenses":    monthly_expenses,
        "monthly_noi":         monthly_noi,
        "annual_noi":          annual_noi,
        "cap_rate":            cap_rate,
        "monthly_cash_flow":   monthly_cash_flow,
        "annual_cash_flow":    annual_cash_flow,
        "closing_costs":       closing_costs,
        "total_cash_invested": total_cash_invested,
        "cash_on_cash":        cash_on_cash,
        "grm":                 grm,
        "one_pct_rule":        one_pct_rule,
        "one_pct_threshold":   one_pct_threshold,
        "deal_score":          score,
    }

    # ── Claude verdict ─────────────────────────────────────────────────
    prompt = f"""You are a seasoned real estate investment analyst. Review this deal and give a clear verdict.

PROPERTY: {address or "Investment Property"}

PURCHASE:
  Price: ${purchase_price:,.0f}
  Down Payment: {down_pct:.0f}% (${down_payment:,.0f})
  Loan: ${loan_amount:,.0f} at {annual_rate:.2f}% for {loan_term_years} years
  Monthly Mortgage: ${monthly_mortgage:,.2f}

INCOME & EXPENSES:
  Gross Monthly Rent: ${monthly_rent:,.0f}
  Vacancy ({vacancy_rate:.0f}%): -${vacancy_loss:,.2f}
  Effective Gross Income: ${effective_gross:,.2f}/mo
  Property Tax: ${monthly_tax:,.0f}/mo
  Insurance: ${monthly_insurance:,.0f}/mo
  Maintenance: ${monthly_maintenance:,.0f}/mo
  Property Management ({mgmt_pct:.0f}%): ${management_fee:,.2f}/mo
  HOA: ${monthly_hoa:,.0f}/mo
  Total Operating Expenses: ${monthly_expenses:,.2f}/mo

KEY METRICS:
  Monthly NOI: ${monthly_noi:,.2f}
  Monthly Cash Flow: ${monthly_cash_flow:,.2f}
  Annual Cash Flow: ${annual_cash_flow:,.2f}
  Cap Rate: {cap_rate:.2f}%
  Cash-on-Cash Return: {cash_on_cash:.2f}%
  GRM: {grm:.1f}
  1% Rule: {"PASSES" if one_pct_rule else "FAILS"} (rent is ${monthly_rent:,.0f}, threshold is ${one_pct_threshold:,.0f})
  Deal Score: {score}/10

Give your analysis using EXACTLY these markers (parsed programmatically):

VERDICT:
[STRONG BUY, PROCEED WITH CAUTION, or PASS — one of these three exact phrases, nothing else]

STRENGTHS:
- [Strength 1 — be specific, reference the actual numbers]
- [Strength 2]
- [Strength 3]

RISKS:
- [Risk 1 — be specific and honest]
- [Risk 2]
- [Risk 3]

IMPROVEMENTS:
- [Improvement 1 — concrete, actionable way to make this deal better]
- [Improvement 2]

SUMMARY:
[2–3 sentences. Overall assessment of this deal. Be direct and specific — reference the actual numbers. No hedging.]

Rules: No markdown, no asterisks. Bullets start with "- ". Be direct."""

    try:
        client   = anthropic.Anthropic()
        response = client.messages.create(
            model=AI_MODEL,
            max_tokens=800,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()

        # Parse Claude response
        keys = ["VERDICT", "STRENGTHS", "RISKS", "IMPROVEMENTS", "SUMMARY"]
        parsed = {}
        for i, key in enumerate(keys):
            marker = f"{key}:"
            start  = raw.find(marker)
            if start == -1:
                parsed[key] = ""
                continue
            start += len(marker)
            end = len(raw)
            for nk in keys[i + 1:]:
                pos = raw.find(f"{nk}:", start)
                if pos != -1:
                    end = pos
                    break
            section = raw[start:end].strip()
            if key in ("STRENGTHS", "RISKS", "IMPROVEMENTS"):
                parsed[key] = [ln.lstrip("- ").strip() for ln in section.splitlines() if ln.strip().startswith("-")]
            else:
                parsed[key] = section

        metrics["verdict"]      = parsed.get("VERDICT", "PROCEED WITH CAUTION")
        metrics["strengths"]    = parsed.get("STRENGTHS", [])
        metrics["risks"]        = parsed.get("RISKS", [])
        metrics["improvements"] = parsed.get("IMPROVEMENTS", [])
        metrics["summary"]      = parsed.get("SUMMARY", "")

        return jsonify({"ok": True, "metrics": metrics})

    except anthropic.AuthenticationError:
        return jsonify({"error": "API key missing. Set ANTHROPIC_API_KEY."}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/listing")
def listing():
    return render_template("listing.html")


@app.route("/api/listing", methods=["POST"])
def api_listing():
    data = request.get_json()

    address  = (data.get("address") or "").strip()
    beds     = (data.get("beds") or "").strip()
    baths    = (data.get("baths") or "").strip()
    sqft     = (data.get("sqft") or "").strip()
    lot      = (data.get("lot") or "N/A").strip()
    year     = (data.get("year_built") or "").strip()
    price    = (data.get("price") or "").strip()
    features = [f.strip() for f in data.get("features", []) if f.strip()]
    vibe     = (data.get("neighborhood_vibe") or "").strip()
    tone     = (data.get("tone") or "Professional").strip()

    if not address or not sqft or len(features) < 3:
        return jsonify({"error": "Please fill in address, sqft, and at least 3 features."}), 400

    tone_desc = {
        "Professional": "polished, precise, and authoritative — like a seasoned real estate professional",
        "Warm/Friendly": "conversational, warm, and approachable — like a trusted friend in real estate",
        "Luxury": "aspirational, evocative, and elevated — like a high-end luxury property brochure",
    }.get(tone, "professional and warm")

    features_text = "\n".join(f"  - {f}" for f in features)

    prompt = f"""You are an expert real estate copywriter. Write THREE compelling MLS listing descriptions for this property.

Tone for all versions: {tone} — {tone_desc}

Property Details:
- Address: {address}
- Bedrooms: {beds} | Bathrooms: {baths}
- Square Footage: {sqft} sq ft | Lot: {lot} | Year Built: {year}
- Price: {price}
- Neighborhood Vibe: {vibe}
- Top Features:
{features_text}

Write exactly 200 words per version. Each must be unique in angle and audience focus.
Use EXACTLY these markers (parsed programmatically):

VERSION_1_LABEL: First-Time Buyers
VERSION_1:
[Focus: affordability, move-in readiness, value, pride of ownership, low-maintenance. No jargon.]

VERSION_2_LABEL: Families
VERSION_2:
[Focus: space, safety, schools, neighborhood community, outdoor areas, room to grow, family lifestyle.]

VERSION_3_LABEL: Investors
VERSION_3:
[Focus: rental income potential, appreciation, location fundamentals, low capex, strong tenant demand.]

Each version must end with a call to action. No titles, no headers inside the descriptions."""

    try:
        client   = anthropic.Anthropic()
        response = client.messages.create(
            model=AI_MODEL,
            max_tokens=1800,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()

        # Parse the three versions
        def extract(text, key):
            marker = f"{key}:"
            start  = text.find(marker)
            if start == -1:
                return ""
            start += len(marker)
            # find the next VERSION_ marker
            import re
            next_match = re.search(r"\nVERSION_\d", text[start:])
            end = start + next_match.start() if next_match else len(text)
            return text[start:end].strip()

        versions = [
            {"label": extract(raw, "VERSION_1_LABEL") or "First-Time Buyers",  "text": extract(raw, "VERSION_1")},
            {"label": extract(raw, "VERSION_2_LABEL") or "Families",            "text": extract(raw, "VERSION_2")},
            {"label": extract(raw, "VERSION_3_LABEL") or "Investors",           "text": extract(raw, "VERSION_3")},
        ]
        return jsonify({"ok": True, "versions": versions, "tone": tone})

    except anthropic.AuthenticationError:
        return jsonify({"error": "API key missing. Set ANTHROPIC_API_KEY."}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/comps")
def comps():
    # Allow pre-filling address from query string (linked from valuation results)
    address = request.args.get("address", "")
    return render_template("comps.html", prefill_address=address)


@app.route("/api/comps", methods=["POST"])
def api_comps():
    data        = request.get_json()
    address     = (data.get("address") or "").strip()
    beds        = (data.get("beds") or "").strip()
    baths       = (data.get("baths") or "").strip()
    sqft        = (data.get("sqft") or "").strip()
    year        = (data.get("year_built") or "").strip()
    price_range = (data.get("price_range") or "").strip()

    if not address:
        return jsonify({"error": "Property address is required."}), 400

    # ── Try Zillow RapidAPI first ─────────────────────────────────────────
    comps_list = []
    data_source = "ai"

    if RAPIDAPI_KEY:
        try:
            location = _extract_location(address)
            raw_results = _fetch_zillow_sold(location, beds, sqft)

            if raw_results:
                # Geocode subject to calculate distances
                subj_lat, subj_lon = _geocode(address)
                comps_list = _format_zillow_comps(raw_results, subj_lat, subj_lon, sqft)

            if comps_list:
                # Add AI-generated comparison notes on top of real data
                comps_list = _add_claude_notes(
                    comps_list, address, beds, baths, sqft, year
                )
                data_source = "zillow"

        except requests.exceptions.HTTPError as e:
            # Log but fall through to Claude fallback
            app.logger.warning(f"Zillow API error: {e}")
        except Exception as e:
            app.logger.warning(f"Zillow fetch failed: {e}")

    # ── Fall back to Claude-generated comps ───────────────────────────────
    if not comps_list:
        prop_details = f"Address: {address}"
        if beds:        prop_details += f"\nBedrooms: {beds}"
        if baths:       prop_details += f"\nBathrooms: {baths}"
        if sqft:        prop_details += f"\nSquare Footage: {sqft} sq ft"
        if year:        prop_details += f"\nYear Built: {year}"
        if price_range: prop_details += f"\nExpected Price Range: {price_range}"

        prompt = f"""You are a licensed real estate appraiser with deep knowledge of local markets. Generate 6 realistic recent comparable sales near the subject property. Base your estimates on the actual market for that city/state.

SUBJECT PROPERTY:
{prop_details}

For each comp use EXACTLY these markers:

COMP_1_ADDRESS:
[Full street address, city, state]
COMP_1_SPECS:
[X bed / X bath / X,XXX sq ft / Built XXXX]
COMP_1_PRICE:
[$XXX,XXX]
COMP_1_DATE:
[Month Year — within last 12 months]
COMP_1_DISTANCE:
[X.X miles away]
COMP_1_NOTES:
[One sentence: key similarity or difference vs subject that affects price. Be specific.]

(continue through COMP_6)

Rules: All 6 in same city/metro. Vary prices realistically. Vary distances 0.2–1.5 miles. No markdown."""

        try:
            client   = anthropic.Anthropic()
            response = client.messages.create(
                model=AI_MODEL, max_tokens=1800,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = response.content[0].text.strip()

            for n in range(1, 7):
                def _get(key, _raw=raw, _n=n):
                    marker = f"COMP_{_n}_{key}:"
                    pos = _raw.find(marker)
                    if pos == -1:
                        return ""
                    start = pos + len(marker)
                    next_m = re.search(r"COMP_\d+_[A-Z]+:", _raw[start:])
                    end = start + next_m.start() if next_m else len(_raw)
                    return _raw[start:end].strip()

                addr = _get("ADDRESS")
                if not addr:
                    continue
                comps_list.append({
                    "address":  addr,
                    "specs":    _get("SPECS"),
                    "price":    _get("PRICE"),
                    "date":     _get("DATE"),
                    "distance": _get("DISTANCE"),
                    "notes":    _get("NOTES"),
                })

        except anthropic.AuthenticationError:
            return jsonify({"error": "API key missing. Set ANTHROPIC_API_KEY."}), 500
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    return jsonify({"ok": True, "comps": comps_list, "subject": address,
                    "source": data_source})


@app.route("/contact", methods=["POST"])
def contact():
    name    = request.form.get("contact_name", "").strip()
    email   = request.form.get("contact_email", "").strip()
    phone   = request.form.get("contact_phone", "").strip()
    message = request.form.get("contact_message", "").strip()
    # In production, send an email here. For now, just confirm.
    flash(f"Thank you {name}! We'll be in touch shortly at {email}.", "success")
    return redirect(url_for("index") + "#contact")


if __name__ == "__main__":
    app.run(debug=True, port=5000)
