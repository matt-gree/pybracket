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
from ..models.tournament import Phase, Qualification, SlotRef, Tournament

__all__ = [
    "bracket_to_dict",
    "bracket_from_dict",
    "bracket_to_json",
    "bracket_from_json",
    "tournament_to_dict",
    "tournament_from_dict",
    "tournament_to_json",
    "tournament_from_json",
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
    # 'bye_rounds' (single_elim) is a seed->count map; JSON turns its int keys into strings,
    # so coerce them back so dict and JSON round-trips agree.
    bye_rounds = out.get("bye_rounds")
    if isinstance(bye_rounds, dict):
        out["bye_rounds"] = {int(k): int(v) for k, v in bye_rounds.items()}
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


def _slotref_to_dict(s: SlotRef) -> dict[str, Any]:
    return {"phase": s.phase, "place": s.place, "group": s.group}


def _slotref_from_dict(d: dict[str, Any]) -> SlotRef:
    return SlotRef(phase=d["phase"], place=d["place"], group=d.get("group"))


def _qualification_to_dict(q: Qualification) -> dict[str, Any]:
    return {"sources": [_slotref_to_dict(s) for s in q.sources], "seeding": q.seeding}


def _qualification_from_dict(d: dict[str, Any]) -> Qualification:
    return Qualification(
        sources=[_slotref_from_dict(s) for s in d["sources"]],
        seeding=d.get("seeding", "snake"),
    )


def _phase_to_dict(p: Phase) -> dict[str, Any]:
    return {
        "id": p.id,
        "format": p.format,
        "config": _config_to_dict(p.config),
        "groups": p.groups,
        "group_assignment": p.group_assignment,
        "state": p.state.value,
        "entrants": None if p.entrants is None else _qualification_to_dict(p.entrants),
        "brackets": [bracket_to_dict(b) for b in p.brackets],
    }


def _phase_from_dict(d: dict[str, Any]) -> Phase:
    entrants = d.get("entrants")
    return Phase(
        id=d["id"],
        format=d["format"],
        config=_config_from_dict(d.get("config", {})),
        entrants=None if entrants is None else _qualification_from_dict(entrants),
        groups=d.get("groups", 1),
        group_assignment=d.get("group_assignment", "snake"),
        brackets=[bracket_from_dict(b) for b in d.get("brackets", [])],
        state=BracketState(d["state"]),
    )


def tournament_to_dict(tournament: Tournament) -> dict[str, Any]:
    """Serialize a Tournament (all phases and their brackets) to a plain dict."""
    return {
        "participants": [_participant_to_dict(p) for p in tournament.participants],
        "config": _config_to_dict(tournament.config),
        "phases": [_phase_to_dict(p) for p in tournament.phases],
    }


def tournament_from_dict(data: dict[str, Any]) -> Tournament:
    """Reconstruct a Tournament from a dict produced by tournament_to_dict."""
    return Tournament(
        phases=[_phase_from_dict(p) for p in data["phases"]],
        participants=[_participant_from_dict(p) for p in data["participants"]],
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


def tournament_to_json(tournament: Tournament) -> str:
    """Serialize a Tournament to a JSON string. Non-JSON-native ids are stringified."""
    return json.dumps(tournament_to_dict(tournament), default=_json_default)


def tournament_from_json(json_str: str) -> Tournament:
    """Reconstruct a Tournament from a JSON string produced by tournament_to_json."""
    return tournament_from_dict(json.loads(json_str))
