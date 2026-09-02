"""The evidence a learned note has to rest on."""

from ghostdriver.ledger import Ledger, Outcome


def outcome(ok, cadence="robot", locator="class=Edit", tool="set_value",
            surface="native"):
    return Outcome(locator=locator, tool=tool, cadence=cadence, ok=ok,
                   surface=surface)


def test_nothing_recorded_is_no_differential():
    assert Ledger().differential("s") is None


def test_a_robot_failure_then_a_paced_success_is_the_differential():
    """The one observation that separates input sensitivity from an
    ordinary validation failure."""
    led = Ledger()
    led.record("s", outcome(False, "robot"))
    led.record("s", outcome(True, "fast_human"))

    found = led.differential("s")

    assert found is not None
    assert found.locator == "class=Edit"
    assert "set_value" in found.describe()


def test_a_paced_success_alone_proves_nothing():
    """Without a robot failure there is no evidence the pacing is what made
    the difference -- the value may simply have been right this time."""
    led = Ledger()
    led.record("s", outcome(True, "fast_human"))

    assert led.differential("s") is None
    assert "nothing failed at robot cadence first" in led.why_not("s")


def test_a_robot_failure_alone_proves_nothing():
    """Failing at speed is what an ordinary validation error looks like."""
    led = Ledger()
    led.record("s", outcome(False, "robot"))

    assert led.differential("s") is None
    assert "cadence=fast_human" in led.why_not("s"), "and says what to try"


def test_the_two_halves_must_be_the_same_action():
    """"Something failed and something else worked" is two unrelated facts,
    not evidence about input speed."""
    led = Ledger()
    led.record("s", outcome(False, "robot", locator="class=Edit"))
    led.record("s", outcome(True, "fast_human", locator="class=Other"))

    assert led.differential("s") is None


def test_the_two_halves_must_be_the_same_tool():
    """A failed click must not vouch for a set_value."""
    led = Ledger()
    led.record("s", outcome(False, "robot", tool="click"))
    led.record("s", outcome(True, "fast_human", tool="set_value"))

    assert led.differential("s") is None


def test_the_experiment_run_backwards_is_the_same_experiment():
    """An agent told a target is sensitive works paced, and may confirm by
    trying robot afterwards. Same evidence, opposite order."""
    led = Ledger()
    led.record("s", outcome(True, "fast_human"))
    led.record("s", outcome(False, "robot"))

    assert led.differential("s") is not None


def test_the_surface_comes_from_where_the_paced_attempt_landed():
    """So the note is recorded against the region that actually needed it,
    not the whole target."""
    led = Ledger()
    led.record("s", outcome(False, "robot", surface="web"))
    led.record("s", outcome(True, "fast_human", surface="web"))

    assert led.differential("s").surface == "web"


def test_evidence_is_scoped_to_one_session():
    """Another session's history says nothing about this one, and a note
    written from it would be unattributable."""
    led = Ledger()
    led.record("a", outcome(False, "robot"))
    led.record("b", outcome(True, "fast_human"))

    assert led.differential("a") is None
    assert led.differential("b") is None


def test_asking_about_one_locator_ignores_the_rest():
    led = Ledger()
    led.record("s", outcome(False, "robot", locator="class=A"))
    led.record("s", outcome(True, "fast_human", locator="class=A"))
    led.record("s", outcome(False, "robot", locator="class=B"))

    assert led.differential("s", "class=A") is not None
    assert led.differential("s", "class=B") is None


def test_the_record_is_bounded():
    """A long session must not grow this without limit; it is working
    evidence, not history."""
    led = Ledger(max_entries=10)
    for _ in range(50):
        led.record("s", outcome(True))

    assert len(led.outcomes("s")) == 10


def test_releasing_a_session_forgets_what_it_saw():
    led = Ledger()
    led.record("s", outcome(False, "robot"))
    led.forget("s")

    assert led.outcomes("s") == []
