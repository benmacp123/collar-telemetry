"""Reduce raw Movebank tag events to the hourly extract that is committed.

The stork studies hold tens of millions of events (1 Hz GPS bursts and an
acceleration burst every few minutes), far more than a repository can
carry. This module turns them into two small tables, both bucketed by UTC
clock hour so the result does not depend on how a download was chunked:

- GPS: the first usable fix of each hour, with the tag's own sensor
  readings, plus how many fixes the hour held.
- Acceleration: one row per hour summarising its bursts (posture as the
  mean per axis, movement as the spread within each burst).

Values stay in raw tag units; nothing is calibrated here. Standard
library only.
"""

import gzip
import math
import statistics
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field

# Bumped whenever a rule below changes what a row holds, so a cached
# download made under an older rule is fetched again.
SCHEMA_VERSION = 1

KEY_COLUMNS = ("individual_id", "deployment_id", "tag_id")

# Copied from the fix as Movebank returned them, text unchanged.
GPS_VALUE_COLUMNS = (
    "timestamp",
    "location_long",
    "location_lat",
    "height_above_ellipsoid",
    "ground_speed",
    "gps_dop",
    "gps_satellite_count",
    "eobs_horizontal_accuracy_estimate",
    "eobs_temperature",
    "eobs_battery_voltage",
    "eobs_activity",
    "eobs_activity_samples",
)
GPS_COLUMNS = KEY_COLUMNS + GPS_VALUE_COLUMNS + ("fixes_in_hour",)

AXES = ("x", "y", "z")
ACC_COLUMNS = (
    KEY_COLUMNS
    + ("hour", "axes", "sampling_frequency", "bursts", "burst_samples")
    + tuple(f"mean_{axis}" for axis in AXES)
    + tuple(f"between_{axis}" for axis in AXES)
    + ("spread_min", "spread_median", "spread_max")
)

# What each reducer asks Movebank for.
GPS_ATTRIBUTES = KEY_COLUMNS + GPS_VALUE_COLUMNS + ("visible",)
ACC_ATTRIBUTES = KEY_COLUMNS + (
    "timestamp",
    "eobs_acceleration_axes",
    "eobs_acceleration_sampling_frequency_per_axis",
    "eobs_accelerations_raw",
    "visible",
)


def hour_of(timestamp: str) -> str:
    """The UTC clock hour a Movebank timestamp falls in.

    Args:
        timestamp: ``yyyy-MM-dd HH:mm:ss.SSS`` text, as Movebank returns it.

    Returns:
        str: The hour's start, as ``yyyy-MM-dd HH:00:00``.

    Raises:
        ValueError: If the text is too short to hold a date and an hour.
    """
    if len(timestamp) < 13 or timestamp[10] != " ":
        raise ValueError(f"not a Movebank timestamp: {timestamp!r}")
    return f"{timestamp[:13]}:00:00"


def _hidden(row: dict) -> bool:
    """Whether Movebank flags a row as an outlier.

    Args:
        row: One event row.

    Returns:
        bool: True when ``visible`` is false; a missing flag means visible.
    """
    return (row.get("visible") or "true").strip().lower() == "false"


def _key(row: dict, hour: str) -> tuple:
    """The bucket an event belongs to.

    Args:
        row: One event row.
        hour: The row's clock hour, from :func:`hour_of`.

    Returns:
        tuple: Animal, deployment, tag and hour.
    """
    return tuple((row.get(column) or "").strip() for column in KEY_COLUMNS) + (hour,)


@dataclass
class GpsReducer:
    """Keeps the first usable fix of each UTC hour.

    Rows may arrive in any order and across several requests; the earliest
    timestamp in a bucket wins, and of two fixes with the same timestamp
    the one seen first.

    Attributes:
        rows: GPS event rows seen.
        not_visible: Rows dropped because Movebank flags them as outliers.
        no_location: Rows dropped for an empty latitude or longitude.
    """

    rows: int = 0
    not_visible: int = 0
    no_location: int = 0
    _first: dict = field(default_factory=dict)
    _count: Counter = field(default_factory=Counter)

    def add(self, row: dict) -> None:
        """Offer one GPS event row.

        Args:
            row: The event, keyed by Movebank attribute name.
        """
        self.rows += 1
        # The same two drops the loader makes, done here so an outlier is
        # never the fix that stands for its hour.
        if _hidden(row):
            self.not_visible += 1
            return
        if (
            not (row.get("location_lat") or "").strip()
            or not (row.get("location_long") or "").strip()
        ):
            self.no_location += 1
            return
        key = _key(row, hour_of(row["timestamp"]))
        self._count[key] += 1
        kept = self._first.get(key)
        if kept is None or row["timestamp"] < kept["timestamp"]:
            self._first[key] = row

    def result(self) -> list[dict]:
        """The reduced rows.

        Returns:
            list[dict]: One row per bucket with ``GPS_COLUMNS``, ordered by
            deployment, tag and time.
        """
        out = []
        for key in sorted(self._first, key=lambda k: (k[1], k[2], k[3], k[0])):
            row = self._first[key]
            reduced = dict(zip(KEY_COLUMNS, key[:3]))
            for column in GPS_VALUE_COLUMNS:
                reduced[column] = (row.get(column) or "").strip()
            reduced["fixes_in_hour"] = str(self._count[key])
            out.append(reduced)
        return out


def summarise_burst(raw: str, axes: str) -> dict | None:
    """Mean and spread of one acceleration burst.

    An e-obs burst is a run of raw readings, one per axis in turn
    (``x y z x y z ...`` for axes ``XYZ``).

    Args:
        raw: The readings, separated by spaces.
        axes: The axes recorded, in order, such as ``XYZ``.

    Returns:
        dict | None: ``samples`` (per axis), ``mean`` (by lower-case axis)
        and ``spread`` (square root of the summed per-axis variances), or
        None when the burst cannot be read: no axes, an unknown axis, a
        non-number, or a length that is not a whole number of samples.
    """
    names = [axis.lower() for axis in axes.strip()]
    if not names or any(name not in AXES for name in names):
        return None
    try:
        values = [int(value) for value in raw.split()]
    except ValueError:
        return None
    if not values or len(values) % len(names):
        return None
    mean, variance = {}, 0.0
    for offset, name in enumerate(names):
        series = values[offset :: len(names)]
        mean[name] = statistics.fmean(series)
        variance += statistics.pvariance(series)
    return {
        "samples": len(values) // len(names),
        "mean": mean,
        "spread": math.sqrt(variance),
    }


@dataclass
class AccReducer:
    """Summarises acceleration bursts by UTC hour.

    A bucket is one animal, deployment and tag in one hour at one axis
    set-up and sampling rate, so a tag reconfigured mid-hour gives two rows
    rather than a mixed one.

    Attributes:
        rows: Acceleration event rows seen.
        not_visible: Rows dropped because Movebank flags them as outliers.
        malformed: Rows whose burst could not be read.
    """

    rows: int = 0
    not_visible: int = 0
    malformed: int = 0
    _bursts: dict = field(default_factory=dict)

    def add(self, row: dict) -> None:
        """Offer one acceleration event row.

        Args:
            row: The event, keyed by Movebank attribute name.
        """
        self.rows += 1
        if _hidden(row):
            self.not_visible += 1
            return
        axes = (row.get("eobs_acceleration_axes") or "").strip()
        burst = summarise_burst(row.get("eobs_accelerations_raw") or "", axes)
        if burst is None:
            self.malformed += 1
            return
        frequency = (
            row.get("eobs_acceleration_sampling_frequency_per_axis") or ""
        ).strip()
        key = _key(row, hour_of(row["timestamp"])) + (axes, frequency)
        self._bursts.setdefault(key, []).append(burst)

    def result(self) -> list[dict]:
        """The reduced rows.

        Returns:
            list[dict]: One row per bucket with ``ACC_COLUMNS``, ordered by
            deployment, tag and time. ``mean_*`` is the mean of the burst
            means; ``between_*`` their standard deviation across the
            hour's bursts (posture change); ``spread_*`` the smallest,
            median and largest within-burst spread (movement). An axis the
            tag did not record is left empty.
        """
        out = []
        for key in sorted(self._bursts, key=lambda k: (k[1], k[2], k[3], k[0], k[4:])):
            bursts = self._bursts[key]
            reduced = dict(zip(KEY_COLUMNS, key[:3]))
            reduced["hour"], reduced["axes"], reduced["sampling_frequency"] = key[3:]
            reduced["bursts"] = str(len(bursts))
            reduced["burst_samples"] = str(
                int(statistics.median_low(burst["samples"] for burst in bursts))
            )
            # All the means, then all the between-burst deviations, to
            # follow ACC_COLUMNS.
            for prefix, measure in (
                ("mean", statistics.fmean),
                ("between", statistics.pstdev),
            ):
                for axis in AXES:
                    means = [b["mean"][axis] for b in bursts if axis in b["mean"]]
                    reduced[f"{prefix}_{axis}"] = (
                        f"{measure(means):.1f}" if means else ""
                    )
            spreads = sorted(burst["spread"] for burst in bursts)
            reduced["spread_min"] = f"{spreads[0]:.2f}"
            reduced["spread_median"] = f"{statistics.median(spreads):.2f}"
            reduced["spread_max"] = f"{spreads[-1]:.2f}"
            out.append(reduced)
        return out


def gzip_member(text: str) -> bytes:
    """Compress text as one gzip member with no timestamp.

    Members can be joined end to end into one valid gzip file, so each
    animal is compressed once and its size is known before parts are
    planned. The zero timestamp keeps the bytes the same on every run.

    Args:
        text: The CSV text to compress.

    Returns:
        bytes: A complete gzip member.
    """
    return gzip.compress(text.encode("utf-8"), compresslevel=9, mtime=0)


def plan_parts(sizes: Iterable[tuple[str, int]], max_bytes: int) -> list[list[str]]:
    """Group blocks into parts no larger than a limit, keeping their order.

    Args:
        sizes: Each block's name and size in bytes, in output order.
        max_bytes: The most a part may hold.

    Returns:
        list[list[str]]: Block names by part; never empty parts.

    Raises:
        ValueError: If one block alone is over the limit.
    """
    parts, used = [], 0
    for name, size in sizes:
        if size > max_bytes:
            raise ValueError(f"{name} alone is {size} bytes, over the limit")
        if not parts or used + size > max_bytes:
            parts.append([])
            used = 0
        parts[-1].append(name)
        used += size
    return parts
