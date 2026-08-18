# Docker Integration Tests

These tests check that EDM can read information from a real Docker container.
They complement the unit tests, which use mock Docker objects and do not connect
to Docker.

## What The Tests Check

The integration suite verifies that EDM can:

- find a running container
- read its logs
- read its environment variables
- load its container and image inspection data
- read its running process information

## How The Test Setup Works

1. Pytest connects to the local Docker daemon.
2. It pulls the small `alpine:3.20` image.
3. It starts one container with a unique name.
4. The container writes a known log message and then remains running.
5. Each test reads part of the container through
   `LocalContainerDataSource`, the same class used by EDM.
6. After all tests finish, pytest removes the container and closes the Docker
   clients. Cleanup also runs when a test fails.

The same container is shared by all five tests. This keeps the suite quick and
avoids repeatedly pulling the image or starting new containers.

## Run The Tests

From the project root, run:

```bash
make integration-test
```

The normal `make test` command runs only unit tests. It does not start a Docker
container.

## Use A Different Image

Set `EDM_INTEGRATION_TEST_IMAGE` to use another Alpine-compatible image:

```bash
EDM_INTEGRATION_TEST_IMAGE=alpine:3.21 make integration-test
```

The image must provide `sh`, `echo`, and `sleep` because the temporary container
uses those commands while the tests run.

## When Docker Is Unavailable

The integration tests are skipped when they cannot connect to local Docker.
Other failures, such as an image pull failure or incorrect data returned by
EDM, fail the test run normally.

GitHub Actions runs this suite on Python 3.12. The workflow checks Docker access
first, so Docker being unavailable in CI causes the job to fail instead of
silently skipping the tests.
