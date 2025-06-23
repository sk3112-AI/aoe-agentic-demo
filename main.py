
from fastapi import FastAPI
from pydantic import BaseModel
from langchain.llms import OpenAI
from langchain.prompts import PromptTemplate
import datetime
import uvicorn
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os
from fastapi.middleware.cors import CORSMiddleware
# ----------------------
# LangChain + OpenAI Setup
# ----------------------
llm = OpenAI(temperature=0.7)

prompt_template = PromptTemplate(
    input_variables=["vehicle", "location", "date", "current_vehicle", "purchase_timeframe"],
    template="""
You are a persuasive automotive sales expert. Create a high-conversion follow-up email for a customer who booked a test drive. Personalize the tone based on vehicle type and urgency. Highlight key features of the vehicle and the value of upgrading from their current brand.

Vehicle: {vehicle}
Location: {location}
Test Drive Date: {date}
Current Vehicle: {current_vehicle}
Time Frame to Purchase: {purchase_timeframe}

Output only the message body, without labels like 'Headline:' or 'Description:'. Avoid repeating "AOE" if already included in the vehicle name.
"""
)

# ----------------------
# FastAPI App Setup
# ----------------------
app = FastAPI()
origins = [
    "https://aoe-motors.lovable.app",
    "http://localhost:3000",
    "http://127.0.0.1:8000"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
class TestDriveRequest(BaseModel):
    fullName: str
    email: str
    phone: str
    vehicle: str
    date: str
    location: str
    current_vehicle: str
    purchase_timeframe: str

# ----------------------
# Email Sending Function
# ----------------------
def send_email(to_email, subject, body):
    sender_email = os.getenv("EMAIL_ADDRESS")
    sender_password = os.getenv("EMAIL_PASSWORD")

    msg = MIMEMultipart()
    msg["From"] = sender_email
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.starttls()
        server.login(sender_email, sender_password)
        server.send_message(msg)

@app.post("/webhook/testdrive")
async def testdrive_handler(payload: TestDriveRequest):
    try:
        prompt = prompt_template.format(
            vehicle=payload.vehicle,
            location=payload.location,
            date=payload.date,
            current_vehicle=payload.current_vehicle,
            purchase_timeframe=payload.purchase_timeframe
        )

        ad_output = llm(prompt).strip()

        vehicle_display_name = payload.vehicle.replace("AOE ", "").replace("AOE", "").strip()
        subject = f"Thank you for booking your AOE {vehicle_display_name} test drive"

        email_body = f"""
Hi {payload.fullName},

Thank you for booking a test drive for the AOE {vehicle_display_name}.

{ad_output}

We look forward to welcoming you for your test drive.

Best,  
AOE Motors
""".strip()

        send_email(
            to_email=payload.email,
            subject=subject,
            body=email_body
        )

        internal_email = os.getenv("TEAM_EMAIL") or "sales@aoemotors.com"
        internal_body = f"""New Test Drive Lead:

Name: {payload.fullName}
Email: {payload.email}
Phone: {payload.phone}
Vehicle: {payload.vehicle}
Location: {payload.location}
Date: {payload.date}
Current Vehicle: {payload.current_vehicle}
Timeframe to Purchase: {payload.purchase_timeframe}

Generated Message:
{ad_output}
""".strip()

        send_email(
            to_email=internal_email,
            subject=f"[New Lead] Test Drive - {payload.vehicle}",
            body=internal_body
        )

        return {
            "customer": payload.fullName,
            "vehicle": payload.vehicle,
            "location": payload.location,
            "preferred_date": payload.date,
            "generated_message": ad_output,
            "timestamp": datetime.datetime.utcnow().isoformat()
        }

    except Exception as e:
        return {"error": str(e)}

@app.get("/preview")
async def preview_ui():
    html_content = """
<html>
    <head><title>AOE Agent Preview</title></head>
    <body style='font-family: Arial;'>
        <h2>AOE Motors - Agentic Ad Generator</h2>
        <p>Submit your test drive form and view results here via /webhook/testdrive</p>
        <p>This is a placeholder UI endpoint. You can extend this to read logs or display ad history.</p>
    </body>
</html>
"""
    return html_content

# ----------------------
# Run the app (local dev only)
# ----------------------
if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
