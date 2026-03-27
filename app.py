"""
property_valuation_app — Premier Realty AI Tools
Flask web app that uses Claude to generate AI property valuations.
"""

import os
import uuid
import json
import io
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, session, send_file, flash

import anthropic
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
        Paragraph("PREMIER REALTY AI TOOLS", s_title),
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
        f"Generated by Premier Realty AI Tools  ·  {generated}  ·  For informational purposes only.",
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

    result_id = str(uuid.uuid4())
    results_store[result_id] = {
        "prop":     prop,
        "comps":    comps,
        "analysis": analysis,
        "generated": datetime.now().strftime("%B %d, %Y"),
    }

    return redirect(url_for("results", result_id=result_id))


@app.route("/results/<result_id>")
def results(result_id):
    data = results_store.get(result_id)
    if not data:
        flash("Report not found or expired. Please submit a new valuation.", "error")
        return redirect(url_for("index"))
    return render_template("results.html", result_id=result_id, **data)


@app.route("/download/<result_id>")
def download(result_id):
    data = results_store.get(result_id)
    if not data:
        flash("Report not found.", "error")
        return redirect(url_for("index"))

    pdf_bytes = build_pdf(data["prop"], data["comps"], data["analysis"])
    address_slug = data["prop"]["address"].replace(" ", "_").replace(",", "")[:40]
    filename = f"Valuation_{address_slug}.pdf"

    return send_file(
        io.BytesIO(pdf_bytes),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=filename,
    )


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
