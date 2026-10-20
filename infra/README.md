# Infrastructure

The serverless deployment (phase 3). Terraform is not written yet; what is
here runs the handlers locally with no AWS account.

## Pipeline

```text
publisher -> SQS FIFO -> processor Lambda -> DynamoDB (state, incidents)
             (group =                         |
              collar)                         stream -> notifier Lambda -> SNS email
                                                                           (likely_death only)
```

- **Messages** (`src/cloud/messages.py`): one collar's slice of simulated
  time (its arrivals in a day, plus "run the clock to the end of the
  day"), with the run, a sequence number, the taxon, the upload plan and
  the boundary name. Messages carry everything the processor needs, so
  no configuration table is required.
- **Idempotency:** each state item records the last sequence number
  applied. The processor writes state and changed incidents in one
  `TransactWriteItems`, conditional on that number, so a redelivered
  message is skipped and a missing one stops its collar instead of being
  stepped over.
- **Outbox:** the notifier reads the incidents table's stream, publishes,
  then marks the incident `notified_at`. A crash before publishing retries
  the send; a crash after publishing and before marking sends a
  duplicate. Notifications go out at least once and are never lost.
  `NOTIFY_ENABLED=true` turns it on, so bulk replays can run silent.

## Local runs

- `lambda/Dockerfile`: one image for both handlers, holding the
  detection core, `src/cloud` and the bundled boundaries.
- `local/compose.yaml`: `motoserver/moto` (SQS, DynamoDB with Streams,
  SNS) plus each handler under the Lambda runtime interface emulator. moto
  does not run the queue and stream triggers, so `src/cloud/local.py`
  polls them from the host and calls the handlers. Batch size, retries
  and dead-lettering are therefore only proven by a real deploy.

```sh
make cloud-local   # build the image, run jackals + 1 vulture, tear down
make cloud-moto    # every study, in-process moto, no Docker
```

Both stop with an error unless every stored incident equals the replay
runner's and each `likely_death` incident sent exactly one notification.

The image's base defaults to the Docker Hub copy of the AWS Lambda Python
image (3.13): `public.ecr.aws` was unreachable from the build machine, and
Docker Hub has no 3.14 tag. That copy dates from January 2025. It is fine
for emulation, but a deploy should build from
`--build-arg BASE=public.ecr.aws/lambda/python:3.14`.
