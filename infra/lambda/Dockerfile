# One image for both handlers; the command picks the handler.
# Build with `make lambda-image`, which exports the requirements first.
#
# The base defaults to the Docker Hub copy of the AWS Lambda Python image:
# public.ecr.aws is unreachable from the owner's network (checked
# 2026-10-20), and Docker Hub has no 3.14 tag. That copy is stale (3.13.0,
# January 2025), which is fine for local emulation. The deploy does not use
# this image: it ships the zip from `make lambda-zip` on the managed
# python3.14 runtime. Where public.ecr.aws is reachable, the maintained
# image can stand in locally:
#   --build-arg BASE=public.ecr.aws/lambda/python:3.14
ARG BASE=amazon/aws-lambda-python:3.13@sha256:01b4aadb2181e2aa473dd7eb8a125de366cbcf77e6aa75cc2b3b719775da49b4
FROM ${BASE}

# The lambda dependency group's versions from uv.lock; `make lambda-image`
# writes it first. No hashes: the lock holds only 3.14 wheels, and this
# base is 3.13.
COPY build/requirements-lambda-image.txt ${LAMBDA_TASK_ROOT}/
RUN pip install --no-cache-dir \
        -r ${LAMBDA_TASK_ROOT}/requirements-lambda-image.txt \
        --target ${LAMBDA_TASK_ROOT}

# Only the core and the cloud package: the handlers import nothing else
# (tests/test_layout.py). The publisher and local harness come along with
# the cloud package but are never imported here.
COPY src/telemetry/__init__.py ${LAMBDA_TASK_ROOT}/telemetry/__init__.py
COPY src/telemetry/core ${LAMBDA_TASK_ROOT}/telemetry/core
COPY src/cloud ${LAMBDA_TASK_ROOT}/cloud
COPY data/raw/boundaries ${LAMBDA_TASK_ROOT}/boundaries
ENV BOUNDARIES_DIR=${LAMBDA_TASK_ROOT}/boundaries

CMD ["cloud.processor.handler"]
