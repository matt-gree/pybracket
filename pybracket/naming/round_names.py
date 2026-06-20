from __future__ import annotations

__all__ = [
    "single_elim_round_name",
    "winners_round_name",
    "losers_round_name",
    "grand_final_round_name",
    "swiss_round_name",
    "round_robin_round_name",
    "gauntlet_round_name",
    "pool_label",
    "pool_round_name",
    "ordinal",
]


def ordinal(n: int) -> str:
    """1 -> '1st', 2 -> '2nd', 3 -> '3rd', 11 -> '11th'."""
    if 10 <= (n % 100) <= 20:
        return f"{n}th"
    suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def single_elim_round_name(round_number: int, total_rounds: int) -> str:
    remaining = total_rounds - round_number
    if remaining == 0:
        return "Final"
    if remaining == 1:
        return "Semifinals"
    if remaining == 2:
        return "Quarterfinals"
    return f"Round {round_number}"


def winners_round_name(round_number: int, total_rounds: int) -> str:
    remaining = total_rounds - round_number
    if remaining == 0:
        return "Winners Finals"
    if remaining == 1:
        return "Winners Semifinals"
    if remaining == 2:
        return "Winners Quarterfinals"
    return f"Winners Round {round_number}"


def losers_round_name(round_number: int, total_rounds: int) -> str:
    remaining = total_rounds - round_number
    if remaining == 0:
        return "Losers Finals"
    return f"Losers Round {round_number}"


def grand_final_round_name(round_number: int) -> str:
    return "Grand Final" if round_number == 1 else "Grand Final Reset"


def swiss_round_name(round_number: int, total_rounds: int | None) -> str:
    if total_rounds is not None and round_number == total_rounds:
        return "Final Round"
    return f"Round {round_number}"


def round_robin_round_name(round_number: int, total_rounds: int) -> str:
    if round_number == total_rounds:
        return "Final Round"
    return f"Round {round_number}"


def matchweek_round_name(matchweek: int, total_matchweeks: int) -> str:
    if matchweek == total_matchweeks:
        return f"Matchweek {matchweek} (Final)"
    return f"Matchweek {matchweek}"


def gauntlet_round_name(round_number: int, total_rounds: int, style: str) -> str:
    if round_number == total_rounds:
        return "Final"
    if style == "single":
        return f"Round {round_number}"
    return single_elim_round_name(round_number, total_rounds)


def pool_label(pool_index: int) -> str:
    """0 -> 'A', 1 -> 'B', ... 26 -> 'AA'."""
    label = ""
    n = pool_index
    while True:
        label = chr(ord("A") + (n % 26)) + label
        n = n // 26 - 1
        if n < 0:
            break
    return label


def pool_round_name(pool_index: int, round_number: int) -> str:
    return f"Pool {pool_label(pool_index)} — Round {round_number}"
