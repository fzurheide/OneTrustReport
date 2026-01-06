import azure.functions as func
import logging
import requests
import os
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import LETTER
from io import BytesIO
import textwrap

app = func.FunctionApp()

# ------------------------------------------------------------
# CONFIGURATION
# ------------------------------------------------------------
BASE_URL = "https://sgr-infosec.my.onetrust.com/api/controls/v1/control-implementations/pages"
ONETRUST_TOKEN = os.getenv("ONETRUST_TOKEN")

HEADERS = {
    "accept": "application/json",
    "content-type": "application/json",
    "authorization": f"Bearer {ONETRUST_TOKEN}"
}

# ------------------------------------------------------------
# FETCH CONTROLS (WITH PAGINATION)
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
        response = requests.post(
            url,
            headers=HEADERS,
            json=payload,
            timeout=60,
            verify=False
        )
        response.raise_for_status()

        data = response.json()
        controls.extend(data.get("content", []))

        total_pages = data.get("totalPages", 1)
        page += 1
        if page >= total_pages:
            break

    return controls

# ------------------------------------------------------------
# SORT IDENTIFIERS NUMERICALLY
# ------------------------------------------------------------
def identifier_key(item):
    identifier = (item.get("control") or {}).get("identifier", "")
    parts = []
    for part in identifier.split("."):
        try:
            parts.append(int(part))
        except ValueError:
            parts.append(0)
    return parts

# ------------------------------------------------------------
# ATTRIBUTE HELPER
# ------------------------------------------------------------
def get_attribute_value(item, key):
    attrs = item.get("attributes") or {}
    values = attrs.get(key) or []

    if not values:
        return "N/A"

    val = values[0].get("value")
    if val in (None, "0", 0):
        return "N/A"

    return val

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

    # Company name
    company_name = "Unknown Company"
    for item in controls:
        control = item.get("control") or {}
        if control.get("orgGroupName"):
            company_name = control["orgGroupName"]
            break
        primary = item.get("primaryEntity") or {}
        if primary.get("name"):
            company_name = primary["name"]
            break

    # Average score
    values = []
    for item in controls:
        v = get_attribute_value(item, "AttributeFormulaValue.value1_2")
        try:
            values.append(float(v))
        except ValueError:
            pass

    avg = sum(values) / len(values) if values else None

    c.setFont("Helvetica-Bold", 14)
    draw(f"OneTrust Controls Summary - {company_name}")
    draw("")

    c.setFont("Helvetica-Bold", 12)
    draw(
        f"Average Score of Applicable Controls: {avg:.2f}"
        if avg is not None
        else "Average Score of Applicable Controls: N/A"
    )
    draw("")

    c.setFont("Helvetica", 10)

    # Controls
    for item in controls:
        control = item.get("control") or {}

        identifier = control.get("identifier", "N/A")
        name = control.get("name", "N/A")
        description = control.get("description", "N/A")

        value = get_attribute_value(item, "AttributeFormulaValue.value1_2")
        effectiveness = (item.get("effectivenessInfo") or {}).get("name", "N/A")

        draw(f"Identifier    : {identifier}")
        draw(f"Name          : {name}")
        draw(f"Description   : {description}")
        draw(f"Value         : {value}")
        draw(f"Effectiveness : {effectiveness}")
        draw("-" * 90)

    c.save()
    buffer.seek(0)
    return buffer

# ------------------------------------------------------------
# HTTP TRIGGER
# ------------------------------------------------------------
@app.route(route="report/{org_id}", auth_level=func.AuthLevel.FUNCTION)
def report(req: func.HttpRequest) -> func.HttpResponse:
    org_id = req.route_params.get("org_id")

    try:
        controls = fetch_controls(org_id)
        pdf = generate_pdf(controls)

        return func.HttpResponse(
            pdf.read(),
            mimetype="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="controls_{org_id}.pdf"'
            }
        )

    except Exception as e:
        logging.exception("Failed to generate report")
        return func.HttpResponse(
            f"Error generating report: {str(e)}",
            status_code=500
        )
