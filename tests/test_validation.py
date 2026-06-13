from __future__ import annotations

import pybracket as pb
import pytest
from pybracket import Participant, ValidationError
from pybracket.utils.validation import (
    ensure_no_duplicate_ids,
    ensure_unique_seeds,
    validate_participants,
)

from tests.helpers import make_participants


def test_too_few_participants_rejected() -> None:
    with pytest.raises(ValidationError):
        validate_participants(make_participants(1))


def test_generate_rejects_single_participant() -> None:
    # The minimum is enforced through the public generation API too.
    with pytest.raises(ValidationError):
        pb.generate_single_elim(make_participants(1))


def test_empty_name_rejected() -> None:
    participants = [
        Participant(id=1, seed=1, name="Alice"),
        Participant(id=2, seed=2, name=""),
    ]
    with pytest.raises(ValidationError):
        validate_participants(participants)


def test_duplicate_ids_rejected() -> None:
    participants = [
        Participant(id=1, seed=1, name="A"),
        Participant(id=1, seed=2, name="B"),
    ]
    with pytest.raises(ValidationError):
        ensure_no_duplicate_ids(participants)
    with pytest.raises(ValidationError):
        validate_participants(participants)


def test_duplicate_seeds_rejected() -> None:
    participants = [
        Participant(id=1, seed=1, name="A"),
        Participant(id=2, seed=1, name="B"),
    ]
    with pytest.raises(ValidationError):
        ensure_unique_seeds(participants)


def test_non_positive_seed_rejected() -> None:
    participants = [
        Participant(id=1, seed=0, name="A"),
        Participant(id=2, seed=1, name="B"),
    ]
    with pytest.raises(ValidationError):
        ensure_unique_seeds(participants)


def test_valid_participants_pass() -> None:
    validate_participants(make_participants(4))  # no exception
