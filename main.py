from fastapi import FastAPI
from pydantic import BaseModel
from langchain.llms import OpenAI
from langchain.prompts import PromptTemplate
from dotenv import load_dotenv
import datetime
import uvicorn
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os
from fastapi.middleware.cors import CORSMiddleware
# ----------------------
# Load environment variables from .env file
# ----------------------
load_dotenv()

# ----------------------
# LangChain + OpenAI Setup
# ----------------------
openai_key = os.getenv("OPENAI_API_KEY")
llm = OpenAI(openai_api_key=openai_key, temperature=0.7)

prompt_template = PromptTemplate(
    input_variables=["vehicle", "location", "date"],
    template="""
    Create a high-conversion test drive Google ad headline and a short, compelling description.

    Vehicle: {vehicle}
    Location: {location}
    Date: {date}

    Format:
    Headline: <headline>
    Description: <description>
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
        # Generate Ad Text
        prompt = prompt_template.format(
            vehicle=payload.vehicle,
            location=payload.location,
            date=payload.date
        )

        ad_output = llm(prompt).strip()

        # Format ad for email
        customer_email_body = f"""
Hi {payload.fullName},

Thank you for booking a test drive for the AOE {payload.vehicle}.

Here’s your personalized ad preview:

{ad_output}

We’ll contact you soon to confirm your appointment.

Best,
AOE Motors
        """

        team_email_body = f"""
New Test Drive Lead Received:

Name: {payload.fullName}
Email: {payload.email}
Phone: {payload.phone}
Vehicle: {payload.vehicle}
Location: {payload.location}
Date: {payload.date}

Generated Ad:
{ad_output}
        """

        # Send emails
        send_email(payload.email, f"Your AOE {payload.vehicle} Test Drive Ad", customer_email_body)

        internal_team_email = os.getenv("TEAM_EMAIL")
        send_email(internal_team_email, f"[New Lead] AOE {payload.vehicle}", team_email_body)

        return {
            "customer": payload.fullName,
            "vehicle": payload.vehicle,
            "generated_ad": ad_output,
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
