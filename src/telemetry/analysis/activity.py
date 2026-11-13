"""The vulture flat-activity cue, as the tag manual states it.

A tag whose activity counter stays constant over two or more transmissions,
while its position does not move, has probably come off or its bird is down.
The rule is frozen in ``config/experiment.toml`` under
``[cues.vulture_flat_activity]`` before any Acopian file is loaded, and it is
not fitted: it has no threshold to choose. This module only carries it out.
"""

from collections.abc import Iterable

from telemetry.analysis.experiment import Experiment


def flat_activity(counts: Iterable[float | None], settings: Experiment) -> bool | None:
    """Whether the activity counter was flat across a stationary run.

    Args:
        counts: The activity count on each transmission inside the alert's
            stationary run; None for a transmission that carried none.
        settings: The experiment file.

    Returns:
        bool | None: True if the readings number at least
        ``min_transmissions`` and differ by no more than ``max_range``;
        False if they number enough but vary more; None if there are too
        few readings to say, which is not the same as not flat.
    """
    cue = settings.cues["vulture_flat_activity"]
    readings = [count for count in counts if count is not None]
    if len(readings) < cue["min_transmissions"]:
        return None
    return max(readings) - min(readings) <= cue["max_range"]
