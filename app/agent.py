import datetime
import json
import logging
import re
import sys
from typing import Any, AsyncGenerator, Dict, List
from pydantic import BaseModel, Field

from google.adk.agents import LlmAgent
from google.adk.agents.context import Context
from google.adk.apps import App
from google.adk.events.event import Event
from google.adk.events.request_input import RequestInput
from functools import cached_property
from google.adk.models import Gemini
from google.adk.tools import AgentTool
from google.adk.tools.mcp_tool import McpToolset
from google.adk.tools.mcp_tool.mcp_session_manager import StdioConnectionParams
from mcp import StdioServerParameters
from google.adk.workflow import Workflow, START, node
from google.genai import types, Client

from app.config import config

class NoVerifyGemini(Gemini):
    @cached_property
    def api_client(self) -> Client:
        import ssl
        ssl_ctx = ssl.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE
        return Client(
            http_options=types.HttpOptions(
                client_args={"verify": ssl_ctx},
                async_client_args={"ssl": ssl_ctx}
            )
        )

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("elderlycareguide")

# ─────────────────────────────────────────────────────────────────────────────
# 1. Specialized Sub-Agent Schemas
# ─────────────────────────────────────────────────────────────────────────────

class MedicationStatus(BaseModel):
    query_type: str = Field(description="Type of query (schedule, compatibility, refill, other)")
    message: str = Field(description="Details and safety advice regarding the medications")

class AppointmentDraft(BaseModel):
    status: str = Field(description="Status of appointment booking (drafted, confirmed, cancelled)")
    clinic_name: str = Field(description="Name of the clinic")
    date: str = Field(description="Date of appointment (YYYY-MM-DD)")
    time: str = Field(description="Time of appointment (HH:MM)")
    message: str = Field(description="Details or confirmation query for the appointment")

class ResourceSearchResults(BaseModel):
    results_found: bool = Field(description="Whether matching resources were found")
    resources: List[Dict[str, Any]] = Field(description="List of resource details matching the search query")
    message: str = Field(description="Summarized description of matching local healthcare resources")

# ─────────────────────────────────────────────────────────────────────────────
# 2. Local Helper Tools (to be augmented with MCP in Phase 3)
# ─────────────────────────────────────────────────────────────────────────────

def check_medication_compatibility(medication_a: str, medication_b: str) -> str:
    """Checks if two medications are safe to take together.
    
    Args:
        medication_a: First medication name.
        medication_b: Second medication name.
    """
    a = medication_a.lower()
    b = medication_b.lower()
    if ("aspirin" in a and "warp" in b) or ("warfarin" in a and "aspirin" in b):
        return "WARNING: High risk of bleeding. Aspirin and Warfarin have a critical interaction. Do not take together without doctor supervision."
    if ("ibuprofen" in a and "aspirin" in b) or ("aspirin" in a and "ibuprofen" in b):
        return "WARNING: Increased risk of stomach ulcers. Use with caution."
    return f"No known major interactions between {medication_a} and {medication_b}."

def get_medication_schedule(patient_name: str) -> str:
    """Gets the logged medication schedule for a patient.
    
    Args:
        patient_name: Name of the patient.
    """
    return (
        f"Medication Schedule for {patient_name}:\n"
        "- Donepezil: 5mg, once daily in the evening (Alzheimer's)\n"
        "- Lisinopril: 10mg, once daily in the morning (Blood Pressure)\n"
        "- Metformin: 500mg, twice daily with meals (Diabetes)"
    )

def draft_appointment(clinic_name: str, date: str, time: str, ctx: Context) -> str:
    """Drafts an appointment schedule for the patient and saves it to state.
    
    Args:
        clinic_name: Name of the clinic or doctor.
        date: Date in YYYY-MM-DD format.
        time: Time in HH:MM format.
    """
    draft = {
        "clinic_name": clinic_name,
        "date": date,
        "time": time,
        "status": "drafted"
    }
    ctx.state["appointment_draft"] = draft
    return f"Appointment drafted successfully at {clinic_name} for {date} at {time}. Status: Requires confirmation."

def confirm_appointment(ctx: Context) -> str:
    """Confirms and logs the drafted appointment.
    """
    draft = ctx.state.get("appointment_draft")
    if not draft:
        return "Error: No drafted appointment found to confirm."
    draft["status"] = "confirmed"
    ctx.state["appointment_booked"] = True
    appointments = ctx.state.get("appointments", [])
    appointments.append(draft)
    ctx.state["appointments"] = appointments
    return f"Appointment at {draft['clinic_name']} on {draft['date']} at {draft['time']} has been officially BOOKED and confirmed."

def cancel_appointment(ctx: Context) -> str:
    """Cancels the drafted appointment.
    """
    ctx.state["appointment_cancelled"] = True
    ctx.state.pop("appointment_draft", None)
    return "The drafted appointment has been cancelled."

def search_local_resources(zip_code: str, resource_type: str) -> str:
    """Search for local healthcare and caregiving resources.
    
    Args:
        zip_code: ZIP code to search within.
        resource_type: Type of resource (e.g. clinic, seniors transport, support group).
    """
    return f"Found local {resource_type} resources near {zip_code}:\n- SeniorCare Transport: 555-0199 (specialized elder mobility)\n- Community Health Center: 555-0120 (walk-in seniors clinic)"

# ─────────────────────────────────────────────────────────────────────────────
# 3. Specialized LlmAgents (Sub-agents)
# ─────────────────────────────────────────────────────────────────────────────

medication_agent = LlmAgent(
    name="medication_agent",
    model=NoVerifyGemini(model=config.model),
    instruction="You are a Medication Specialist. You assist with tracking medication schedules, dosage instructions, pill compatibility, and refill reminders. Use the compatibility, schedule, and refill status tools to provide safe recommendations.",
    tools=[
        check_medication_compatibility,
        get_medication_schedule,
        McpToolset(
            connection_params=StdioConnectionParams(
                server_params=StdioServerParameters(
                    command=sys.executable,
                    args=["-m", "app.mcp_server"],
                ),
            ),
            tool_filter=["get_refill_status"],
        ),
    ],
    output_schema=MedicationStatus,
    output_key="medication_status",
)

appointment_agent = LlmAgent(
    name="appointment_agent",
    model=NoVerifyGemini(model=config.model),
    instruction="You are an Appointment Specialist. You help coordinate clinic visits, check schedules, and manage appointments. If booking an appointment, call get_doctor_availability to see matching slots, and call draft_appointment to draft it.",
    tools=[
        draft_appointment,
        confirm_appointment,
        cancel_appointment,
        McpToolset(
            connection_params=StdioConnectionParams(
                server_params=StdioServerParameters(
                    command=sys.executable,
                    args=["-m", "app.mcp_server"],
                ),
            ),
            tool_filter=["get_doctor_availability"],
        ),
    ],
    output_schema=AppointmentDraft,
    output_key="appointment_status",
)

resource_agent = LlmAgent(
    name="resource_agent",
    model=NoVerifyGemini(model=config.model),
    instruction="You are a Healthcare Resource Specialist. You help locate local resources such as clinics, eldercare services, seniors' support groups, and transport options. Use search_local_resources and search_local_clinics to find matching listings.",
    tools=[
        McpToolset(
            connection_params=StdioConnectionParams(
                server_params=StdioServerParameters(
                    command=sys.executable,
                    args=["-m", "app.mcp_server"],
                ),
            ),
            tool_filter=["search_local_clinics", "search_elder_transport"],
        )
    ],
    output_schema=ResourceSearchResults,
    output_key="resource_status",
)

# ─────────────────────────────────────────────────────────────────────────────
# 4. Orchestrator Agent (Delegator)
# ─────────────────────────────────────────────────────────────────────────────

orchestrator_agent = LlmAgent(
    name="orchestrator_agent",
    model=NoVerifyGemini(model=config.model),
    instruction=(
        "You are the ElderlyCareGuide Orchestrator. You help elderly individuals and caregivers manage medications, schedule clinic appointments, and search local healthcare resources. "
        "Delegate tasks to your sub-agents: `medication_agent` (for medication logs, schedules, and drug interactions), "
        "`appointment_agent` (for drafting/booking appointments), and `resource_agent` (for searching local eldercare services). "
        "If a sub-agent drafts an appointment or requires confirmation, ask the user clearly to confirm."
    ),
    tools=[AgentTool(medication_agent), AgentTool(appointment_agent), AgentTool(resource_agent)],
)

# ─────────────────────────────────────────────────────────────────────────────
# 5. Workflow Node Functions
# ─────────────────────────────────────────────────────────────────────────────

@node
def security_checkpoint(ctx: Context, node_input: Any) -> Event:
    text_input = ""
    if isinstance(node_input, str):
        text_input = node_input
    elif hasattr(node_input, "parts") and node_input.parts:
        text_input = "".join(part.text for part in node_input.parts if part.text)
    elif isinstance(node_input, dict) and "parts" in node_input:
        parts = node_input["parts"]
        text_input = "".join(part.get("text", "") for part in parts if isinstance(part, dict) and "text" in part)
    elif node_input:
        text_input = str(node_input)
    
    # Injection Detection
    injection_keywords = ["ignore previous instructions", "system prompt", "override rules", "bypass checkpoint"]
    detected_injection = any(kw in text_input.lower() for kw in injection_keywords)
    
    # PII Scrubbing
    clean_input = text_input
    clean_input = re.sub(r'\b\d{3}-\d{2}-\d{4}\b', '[REDACTED SSN]', clean_input)
    clean_input = re.sub(r'\b\d{3}-\d{3}-\d{4}\b', '[REDACTED PHONE]', clean_input)
    clean_input = re.sub(r'\b\d{4}-\d{4}-\d{4}-\d{4}\b', '[REDACTED CARD]', clean_input)
    
    ctx.state["clean_input"] = clean_input
    
    # Domain Consent Rule
    consent_keywords = ["medical record", "health history", "patient file"]
    has_restricted_terms = any(kw in text_input.lower() for kw in consent_keywords)
    consent_given = "consent" in text_input.lower() or "authorized" in text_input.lower() or ctx.state.get("caregiver_consented", False)
    
    security_error_message = ""
    if detected_injection:
        security_error_message = "Security Warning: Potential prompt injection attempt detected. Request blocked."
        severity = "CRITICAL"
    elif has_restricted_terms and not consent_given:
        security_error_message = "Security Warning: Caregiver authorization or user consent is required to access patient history files."
        severity = "WARNING"
    else:
        severity = "INFO"
        
    audit_log = {
        "timestamp": datetime.datetime.now().isoformat(),
        "session_id": ctx.session.id,
        "severity": severity,
        "detected_injection": detected_injection,
        "restricted_terms": has_restricted_terms,
        "consent_given": consent_given,
        "cleaned_input": clean_input != text_input
    }
    logger.info(f"[AUDIT LOG] {json.dumps(audit_log)}")
    
    if security_error_message:
        return Event(output=security_error_message, route="SECURITY_EVENT", state={"security_audit": audit_log})
    
    return Event(output=clean_input, route="PASS", state={"security_audit": audit_log})

@node
def security_handler(node_input: str) -> Event:
    return Event(
        content=types.Content(
            role="model",
            parts=[types.Part.from_text(text=node_input)]
        ),
        output=node_input
    )

@node(rerun_on_resume=True)
async def orchestrator_node(ctx: Context, node_input: Any) -> Event:
    query = ctx.state.get("clean_input", "")
    
    # Process confirmation input if we were pending one
    if ctx.state.get("pending_confirmation", False):
        confirmation_answer = ctx.state.get("confirmation_answer", "")
        query = f"The user responded to the confirmation prompt with: '{confirmation_answer}'. If they confirmed, finalize the appointment booking. If they denied, cancel it."
        ctx.state["pending_confirmation"] = False
        ctx.state["confirmation_answer"] = ""
        
    agent_input = types.Content(
        role="user",
        parts=[types.Part.from_text(text=query)]
    )
    
    response = await ctx.run_node(orchestrator_agent, node_input=agent_input)
    response_text = ""
    if response and hasattr(response, "parts") and response.parts:
        response_text = "".join(part.text for part in response.parts if part.text)
        response_content = response
    elif isinstance(response, str):
        response_text = response
        response_content = types.Content(
            role="model",
            parts=[types.Part.from_text(text=response)]
        )
    else:
        response_text = str(response)
        response_content = types.Content(
            role="model",
            parts=[types.Part.from_text(text=response_text)]
        )
        
    # Check if a draft appointment requires human confirmation
    draft = ctx.state.get("appointment_draft")
    if draft and not ctx.state.get("appointment_booked", False) and not ctx.state.get("appointment_cancelled", False):
        ctx.state["pending_confirmation"] = True
        return Event(
            output=response_text,
            route="NEEDS_CONFIRMATION",
            content=response_content
        )
        
    return Event(
        output=response_text,
        route="COMPLETE",
        content=response_content
    )

@node
async def human_confirmation_node(ctx: Context, node_input: str) -> AsyncGenerator[Any, Any]:
    interrupt_id = f"confirm_booking_{ctx.session.id}"
    
    if not ctx.resume_inputs or interrupt_id not in ctx.resume_inputs:
        yield RequestInput(
            interrupt_id=interrupt_id,
            message="Would you like to confirm this appointment booking? Please reply 'yes' to book or 'no' to cancel."
        )
        return
        
    user_response = ctx.resume_inputs[interrupt_id]
    ctx.state["confirmation_answer"] = user_response
    yield Event(output=user_response, route="RESUMED")

@node
def final_output_node(ctx: Context, node_input: str) -> Event:
    # Cleanup state transitions
    ctx.state.pop("appointment_draft", None)
    ctx.state.pop("appointment_booked", None)
    ctx.state.pop("appointment_cancelled", None)
    
    return Event(
        content=types.Content(
            role="model",
            parts=[types.Part.from_text(text=node_input)]
        ),
        output=node_input
    )

# ─────────────────────────────────────────────────────────────────────────────
# 6. Workflow / Graph Definition
# ─────────────────────────────────────────────────────────────────────────────

root_agent = Workflow(
    name="root_agent",
    edges=[
        (START, security_checkpoint),
        (security_checkpoint, {"SECURITY_EVENT": security_handler, "PASS": orchestrator_node}),
        (orchestrator_node, {"NEEDS_CONFIRMATION": human_confirmation_node, "COMPLETE": final_output_node}),
        (human_confirmation_node, {"RESUMED": orchestrator_node}),
    ],
    description="Elderly Care Coordinator Workflow Agent",
)

app = App(
    root_agent=root_agent,
    name="app",
)
