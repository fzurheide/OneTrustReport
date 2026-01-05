import azure.functions as func
import requests
import os
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import LETTER
from io import BytesIO
import textwrap

app = func.FunctionApp()

BASE_URL = "https://sgr-infosec.my.onetrust.com/api/controls/v1/control-implementations/pages"
ONETRUST_TOKEN = os.getenv("ONETRUST_TOKEN")

HEADERS = {
    "accept": "application/json",
    "content-type": "application/json",
    "authorization": f"Bearer {ONETRUST_TOKEN}"
}

# ------------------------------------------------------------
# FETCH CONTROLS
# ------------------------------------------------------------
def fetch_controls(org_id):
    controls = []
    page = 0
    size = 50

    while True:
        payload = {
            "filters": [
                {
                    "field": "organizationId",
                    "operator": "EQUAL_TO",
                    "value": org_id
                }
            ]
        }

        url = f"{BASE_URL}?page={page}&size={size}"
        r = requests.post(url, headers=HEADERS, json=payload, timeout=60)
        r.raise_for_status()

        data = r.json()
        controls.extend(data.get("content", []))

        if page + 1 >= data.get("totalPages", 1):
            break
        page += 1

    return controls

# ------------------------------------------------------------
# SORTING
# ------------------------------------------------------------
def identifier_key(item):
    identifier = (item.get("control") or {}).get("identifier", "")
    parts = []
    for p in identifier.split("."):
        try:
            parts.append(int(p))
        except ValueError:
            parts.append(0)
    return parts

# ------------------------------------------------------------
# PDF GENERATION
# ------------------------------------------------------------
def generate_pdf(controls):
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=LETTER)

    width, height = LETTER
    x_margin = 40
    y_margin = 40
    y = height - y_margin
    line_height = 14

    def draw(text):
        nonlocal y
        for line in textwrap.wrap(text, 100):
            if y <= y_margin:
                c.showPage()
                c.setFont("Helvetica", 10)
                y = height - y_margin
            c.drawString(x_margin, y, line)
            y -= line_height

    controls.sort(key=identifier_key)

    c.setFont("Helvetica-Bold", 14)
    draw("OneTrust Controls Summary")
    y -= 20

    c.setFont("Helvetica", 10)

    for item in controls:
        control = item.get("control") or {}
        draw(f"Identifier: {control.get('identifier', 'N/A')}")
        draw(f"Name: {control.get('name', 'N/A')}")
        draw(f"Description: {control.get('description', 'N/A')}")
        draw("-" * 90)

    c.save()
    buffer.seek(0)
    return buffer.read()

# ------------------------------------------------------------
# HTTP ENDPOINT
# ------------------------------------------------------------
@app.route(route="report/{org_id}", methods=["GET"])
def report(req: func.HttpRequest) -> func.HttpResponse:
    org_id = req.route_params.get("org_id")

    if not org_id:
        return func.HttpResponse("Missing org_id", status_code=400)

    try:
        controls = fetch_controls(org_id)
        pdf_bytes = generate_pdf(controls)

        return func.HttpResponse(
            body=pdf_bytes,
            mimetype="application/pdf",
            headers={
                "Content-Disposition": f"attachment; filename=controls_{org_id}.pdf"
            }
        )
    except Exception as e:
        return func.HttpResponse(str(e), status_code=500)
