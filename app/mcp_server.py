import logging
from mcp.server.fastmcp import FastMCP

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("elderlycare-mcp")

# Initialize FastMCP Server
mcp = FastMCP("elderlycare-mcp")

@mcp.tool()
def search_local_clinics(zip_code: str) -> str:
    """Finds clinics matching eldercare needs in the given zip code.
    
    Args:
        zip_code: ZIP code to search.
    """
    logger.info(f"MCP: Searching clinics in ZIP code: {zip_code}")
    # Simulating clinic results
    return (
        f"Healthcare Clinics for Seniors in {zip_code}:\n"
        "- Geriatric Health Associates: 123 Careway Lane, Phone: 555-0101 (Specializes in age-related care and Alzheimer's support)\n"
        "- Family & Elder Primary Care: 789 Wellness Blvd, Phone: 555-0102 (Offering walk-in geriatric consults)"
    )

@mcp.tool()
def get_refill_status(prescription_id: str) -> str:
    """Checks the status of a medication refill request.
    
    Args:
        prescription_id: The ID of the prescription to query.
    """
    logger.info(f"MCP: Querying refill status for prescription: {prescription_id}")
    # Simulating prescription database lookup
    pid = prescription_id.upper()
    if "RX" not in pid:
        return "Invalid prescription format. Please provide a valid ID starting with 'RX' (e.g. RX1092)."
    
    if hash(pid) % 2 == 0:
        return f"Prescription {prescription_id} refill status: READY FOR PICKUP at Pharmacy Counter A. Copay: $5.00."
    return f"Prescription {prescription_id} refill status: OUT OF REFILLS. Request sent to Doctor Smith for approval."

@mcp.tool()
def search_elder_transport(zip_code: str) -> str:
    """Finds non-emergency senior transportation services in the given zip code.
    
    Args:
        zip_code: ZIP code to search.
    """
    logger.info(f"MCP: Searching senior transport in ZIP code: {zip_code}")
    return (
        f"Senior Mobility & Transportation Services in {zip_code}:\n"
        "- SilverRide Mobility: Phone: 555-0199 (Door-to-door escort services for seniors, medical appointment transport)\n"
        "- County Care Shuttle: Phone: 555-0210 (Free community transit for ages 65+ to clinics/supermarkets)"
    )

@mcp.tool()
def get_doctor_availability(doctor_name: str) -> str:
    """Gets the next available scheduling slots for a specific physician.
    
    Args:
        doctor_name: Name of the doctor.
    """
    logger.info(f"MCP: Querying availability for doctor: {doctor_name}")
    doc = doctor_name.lower()
    if "smith" in doc:
        return f"Doctor Smith (Geriatrics) Availability:\n- Tomorrow, 10:00 AM\n- Tomorrow, 11:30 AM\n- Friday, 2:00 PM"
    if "jones" in doc:
        return f"Doctor Jones (Cardiology) Availability:\n- Thursday, 9:00 AM\n- Friday, 4:00 PM"
    return f"Doctor '{doctor_name}' is available Monday through Friday from 9:00 AM to 5:00 PM. Please call 555-0150 to book."

if __name__ == "__main__":
    mcp.run()
