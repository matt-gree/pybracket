from __future__ import annotations

from collections.abc import Callable

import pytest
from hypothesis import strategies as st
from pybracket import Bracket, Participant

from .helpers import make_participants, simulate


@pytest.fixture
def participants_factory() -> Callable[[int], list[Participant]]:
    return make_participants


@pytest.fixture
def p2() -> list[Participant]:
    return make_participants(2)


@pytest.fixture
def p4() -> list[Participant]:
    return make_participants(4)


@pytest.fixture
def p8() -> list[Participant]:
    return make_participants(8)


@pytest.fixture
def p16() -> list[Participant]:
    return make_participants(16)


@pytest.fixture
def simulate_fn() -> Callable[..., Bracket]:
    return simulate


# Hypothesis strategy: valid participant lists of varying sizes.
@st.composite
def participant_lists(draw: st.DrawFn, min_size: int = 2, max_size: int = 33) -> list[Participant]:
    n = draw(st.integers(min_value=min_size, max_value=max_size))
    return make_participants(n)
