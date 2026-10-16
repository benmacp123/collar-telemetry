# Collar Telemetry

Can a small, cheap, serverless pipeline turn raw GPS-collar fixes into
alerts a ranger can trust?

This project builds an alerting pipeline for wildlife GPS collars: it
cleans late, duplicated and out-of-order fixes, and raises alerts for
possible deaths, geofence breaches, unusual movement and silent collars.
The same detection core runs locally against replayed public data and on
AWS as a serverless stack deployed with Terraform.

**Status: planning.**

## Development

```
make install
make test
make lint
make format-check
```
