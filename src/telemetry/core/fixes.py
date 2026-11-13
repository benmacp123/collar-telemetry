"""Core records: a collar deployment, the GPS fixes it produces and their
arrival at the pipeline."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Deployment:
    """One tag on one animal for one period.

    Per-animal state is keyed on ``deployment_id``, never on the tag:
    collars are recovered from dead animals and fitted to new ones.

    Attributes:
        deployment_id: Unique identifier for the deployment.
        tag_id: Identifier of the physical tag.
        animal_id: Identifier of the animal wearing the tag.
        taxon: Scientific name of the animal's taxon.
        deploy_on: Start of the deployment (UTC).
        deploy_off: End of the deployment (UTC), or None if open-ended.
        end_type: Movebank ``deployment-end-type`` (e.g. "dead"), or None.
    """

    deployment_id: str
    tag_id: str
    animal_id: str
    taxon: str
    deploy_on: datetime
    deploy_off: datetime | None
    end_type: str | None

    def covers(self, timestamp: datetime) -> bool:
        """Whether a fix at ``timestamp`` belongs to this deployment.

        Follows Movebank's rule: fixes before deploy-on or after deploy-off
        are not associated with the animal.

        Args:
            timestamp: Time of the fix (UTC).

        Returns:
            True if the timestamp falls inside the deployment, inclusive.
        """
        if timestamp < self.deploy_on:
            return False
        return self.deploy_off is None or timestamp <= self.deploy_off


# Optional per-fix tag readings, in the order ``Fix`` declares them.
SENSOR_FIELDS = ("activity", "temperature", "hdop", "voltage")


@dataclass(frozen=True)
class Fix:
    """A single GPS position report.

    Attributes:
        deployment_id: Deployment the fix belongs to.
        timestamp: Time the fix was taken (UTC).
        lat: Latitude in decimal degrees (WGS84).
        lon: Longitude in decimal degrees (WGS84).
        activity: The tag's activity count for the fix's interval, or None.
        temperature: Tag temperature in degrees Celsius, or None.
        hdop: Horizontal dilution of precision, or None.
        voltage: Tag battery voltage (millivolts on e-obs tags), or None.
    """

    deployment_id: str
    timestamp: datetime
    lat: float
    lon: float
    activity: float | None = None
    temperature: float | None = None
    hdop: float | None = None
    voltage: float | None = None

    def to_dict(self) -> dict:
        """JSON-ready form, for state saved between invocations.

        Sensor fields are written only when set, so a fix without sensor
        data serialises exactly as it did before they existed and saved
        state stays byte-identical.

        Returns:
            dict: The fix's fields, with the timestamp as ISO 8601 text.
        """
        data = {
            "deployment_id": self.deployment_id,
            "timestamp": self.timestamp.isoformat(),
            "lat": self.lat,
            "lon": self.lon,
        }
        for name in SENSOR_FIELDS:
            value = getattr(self, name)
            if value is not None:
                data[name] = value
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "Fix":
        """Rebuild a fix saved with ``to_dict``.

        Args:
            data: A dict produced by ``Fix.to_dict``.

        Returns:
            Fix: The equivalent fix.
        """
        return cls(
            data["deployment_id"],
            datetime.fromisoformat(data["timestamp"]),
            data["lat"],
            data["lon"],
            **{name: data[name] for name in SENSOR_FIELDS if name in data},
        )


@dataclass(frozen=True)
class Arrival:
    """One fix reaching the pipeline.

    Attributes:
        time: When the fix arrives.
        fix: The fix itself, unchanged.
    """

    time: datetime
    fix: Fix
