"""Persona + society config loaders (D9: identity + shared voting protocol)."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass
class Persona:
    id: str
    role: str
    leaning: str  # "restrictive" | "permissive"
    system_prompt: str  # composed: identity + voting protocol


@dataclass
class SocietyConfig:
    name: str
    description: str
    voting_rule: str  # "simple_majority" | "none"
    members: list[Persona]
    visibility: str = "prompt-and-response"  # "prompt-and-response" | "response-only" (D24)


# Map a society's visibility to the personas.yaml key holding the matching voting
# protocol. "response-only" (v2/D24) blinds the committee to the user prompt, so
# it needs a protocol whose Input section names only the candidate response.
_PROTOCOL_KEY = {
    "prompt-and-response": "voting_protocol",
    "response-only": "voting_protocol_response_only",
}


def _load_personas(
    personas_path: Path, visibility: str = "prompt-and-response"
) -> dict[str, Persona]:
    data = yaml.safe_load(personas_path.read_text())
    protocol_key = _PROTOCOL_KEY.get(visibility)
    if protocol_key is None:
        raise ValueError(
            f"Unknown visibility '{visibility}'; expected one of {sorted(_PROTOCOL_KEY)}"
        )
    if protocol_key not in data:
        raise KeyError(
            f"personas file {personas_path} has no '{protocol_key}' "
            f"(required for visibility '{visibility}')"
        )
    protocol = data[protocol_key]
    personas: dict[str, Persona] = {}
    for pid, pdata in data["personas"].items():
        composed = pdata["system_prompt"].rstrip() + "\n\n" + protocol
        personas[pid] = Persona(
            id=pid,
            role=pdata["role"],
            leaning=pdata["leaning"],
            system_prompt=composed,
        )
    return personas


def load_society(society_path: Path, personas_path: Path | None = None) -> SocietyConfig:
    """Load a society YAML config. Defaults personas_path to <same dir>/personas.yaml."""
    society_path = Path(society_path)
    if personas_path is None:
        personas_path = society_path.parent / "personas.yaml"

    data = yaml.safe_load(society_path.read_text())
    visibility = data.get("visibility", "prompt-and-response")
    personas_by_id = _load_personas(Path(personas_path), visibility)

    member_ids = data.get("members") or []
    members: list[Persona] = []
    for mid in member_ids:
        if mid not in personas_by_id:
            raise KeyError(f"Unknown persona id '{mid}' referenced in {society_path}")
        members.append(personas_by_id[mid])

    return SocietyConfig(
        name=data["name"],
        description=data.get("description", ""),
        voting_rule=data["voting_rule"],
        members=members,
        visibility=visibility,
    )
