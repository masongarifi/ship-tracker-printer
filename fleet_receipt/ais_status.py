from typing import Any, Dict


AIS_NAVIGATIONAL_STATUSES: Dict[int, str] = {
    0: "Under way",
    1: "At anchor",
    2: "Not under command",
    3: "Restricted manoeuvrability",
    4: "Constrained by her draught",
    5: "Moored",
    6: "Aground",
    7: "Engaged in fishing",
    8: "Under way under sailing only",
    9: "Reserved for future use",
    10: "Reserved for future use",
    11: "Power driven vessel towing astern",
    12: "Power driven vessel pushing ahead or towing alongside",
    13: "Reserved for future use",
    14: "AIS SART, MOB AIS, or EPIRB AIS active",
    15: "Undefined / default",
}


def navigational_status(value: Any) -> str:
    """Translate an AIS status code while preserving already-readable status text."""
    if isinstance(value, bool):
        return "Navigational status unavailable"
    if isinstance(value, int):
        return AIS_NAVIGATIONAL_STATUSES.get(value, "Navigational status unavailable")
    if isinstance(value, str):
        cleaned = value.strip()
        if cleaned.isdigit():
            return AIS_NAVIGATIONAL_STATUSES.get(
                int(cleaned), "Navigational status unavailable"
            )
        return cleaned or "Navigational status unavailable"
    return "Navigational status unavailable"
