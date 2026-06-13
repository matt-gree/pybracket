from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from ..models.bracket import Bracket
from ..models.enums import (
    AdvancementType,
    BracketSide,
    BracketState,
    MatchStatus,
    PairingMethod,
)
from ..models.match import Match
from ..models.participant import Participant
from ..models.round import Round

__all__ = [
    "bracket_to_dict",
    "bracket_from_dict",
    "bracket_to_json",
    "bracket_from_json",
]


def _participant_to_dict(p: Participant) -> dict[str, Any]:
    return {"id": p.id, "seed": p.seed, "name": p.name, "stats": dict(p.stats)}


def _participant_from_dict(d: dict[str, Any]) -> Participant:
    return Participant(id=d["id"], seed=d["seed"], name=d["name"], stats=dict(d.get("stats", {})))


def _match_to_dict(m: Match) -> dict[str, Any]:
    return {
        "id": m.id,
        "round_number": m.round_number,
        "bracket_side": m.bracket_side.value,
        "participant1_id": m.participant1_id,
        "participant2_id": m.participant2_id,
        "winner_id": m.winner_id,
        "loser_id": m.loser_id,
        "advancement_type": m.advancement_type.value if m.advancement_type else None,
        "next_winner_match_id": m.next_winner_match_id,
        "next_loser_match_id": m.next_loser_match_id,
        "status": m.status.value,
        "best_of": m.best_of,
        "metadata": dict(m.metadata),
    }


def _match_from_dict(d: dict[str, Any]) -> Match:
    adv = d.get("advancement_type")
    return Match(
        id=d["id"],
        round_number=d["round_number"],
        bracket_side=BracketSide(d["bracket_side"]),
        participant1_id=d["participant1_id"],
        participant2_id=d["participant2_id"],
        winner_id=d["winner_id"],
        loser_id=d["loser_id"],
        advancement_type=AdvancementType(adv) if adv else None,
        next_winner_match_id=d["next_winner_match_id"],
        next_loser_match_id=d["next_loser_match_id"],
        status=MatchStatus(d["status"]),
        best_of=d.get("best_of", 1),
        metadata=dict(d.get("metadata", {})),
    )


def _round_to_dict(r: Round) -> dict[str, Any]:
    return {
        "number": r.number,
        "bracket_side": r.bracket_side.value,
        "match_ids": list(r.match_ids),
        "name": r.name,
        "best_of": r.best_of,
    }


def _round_from_dict(d: dict[str, Any]) -> Round:
    return Round(
        number=d["number"],
        bracket_side=BracketSide(d["bracket_side"]),
        match_ids=list(d["match_ids"]),
        name=d["name"],
        best_of=d.get("best_of"),
    )


def _config_to_dict(config: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in config.items():
        if isinstance(value, PairingMethod):
            out[key] = value.value
        else:
            out[key] = value
    return out


def _config_from_dict(config: dict[str, Any]) -> dict[str, Any]:
    out = dict(config)
    # 'pairing_method' is the only enum-typed config key (Swiss).
    pm = out.get("pairing_method")
    if isinstance(pm, str):
        out["pairing_method"] = PairingMethod(pm)
    return out


def bracket_to_dict(bracket: Bracket) -> dict[str, Any]:
    """Serialize a Bracket to a plain dict. Any-typed ids are preserved as-is."""
    return {
        "format": bracket.format,
        "state": bracket.state.value,
        "participants": [_participant_to_dict(p) for p in bracket.participants],
        "matches": [_match_to_dict(m) for m in bracket.matches],
        "rounds": [_round_to_dict(r) for r in bracket.rounds],
        "config": _config_to_dict(bracket.config),
    }


def bracket_from_dict(data: dict[str, Any]) -> Bracket:
    """Reconstruct a Bracket from a dict produced by bracket_to_dict."""
    return Bracket(
        format=data["format"],
        state=BracketState(data["state"]),
        participants=[_participant_from_dict(p) for p in data["participants"]],
        matches=[_match_from_dict(m) for m in data["matches"]],
        rounds=[_round_from_dict(r) for r in data["rounds"]],
        config=_config_from_dict(data.get("config", {})),
    )


def _json_default(obj: Any) -> Any:
    if isinstance(obj, UUID):
        return str(obj)
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def bracket_to_json(bracket: Bracket) -> str:
    """Serialize a Bracket to a JSON string. Non-JSON-native ids (e.g. UUID) are stringified."""
    return json.dumps(bracket_to_dict(bracket), default=_json_default)


def bracket_from_json(json_str: str) -> Bracket:
    """Reconstruct a Bracket from a JSON string produced by bracket_to_json."""
    return bracket_from_dict(json.loads(json_str))
