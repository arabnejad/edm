# Platform Smoke Tests

These tests check that the built EDM package works on Windows and macOS. They
focus on startup problems that may not appear in the Linux unit tests.

## What The Tests Check

The smoke suite verifies that:

- the installed package contains every EDM module
- installation creates the `edm` console command
- `edm --help` and `edm --version` run successfully
- `python -m easy_docker_manager` reaches the same command-line interface
- config and log files use the operating system's user config directory
- Windows selects the polling background notifier
- macOS selects the pipe background notifier
- EDM can complete basic startup and shutdown without opening a real terminal

The startup test replaces Docker with a fake client that returns one sample
container, logs, environment variables, inspection data, and a process table.
It also replaces Urwid's interactive event loop with one that returns
immediately. The rest of `EDMApp` uses the normal application code.

## Run The Tests Locally

Install the current project, then run:

```bash
python -m pip install --group test -e .
make smoke-test
```

A local run checks the operating system currently in use. GitHub Actions runs
the same tests against the built wheel on real Windows and macOS runners using
Python 3.12.

## Local Runs And GitHub Actions

`make smoke-test` does not download or emulate another operating system. If you
run it on Linux, it checks the Linux installation and selects the Unix pipe
notifier. Running the same command on Windows checks the Windows installation
and selects the polling notifier.

After you push a branch, the Package workflow performs the cross-platform
checks. It builds the EDM wheel once and then:

1. starts a GitHub-hosted Windows runner, installs the wheel, and runs the
   smoke tests
2. starts a GitHub-hosted macOS runner, installs the same wheel, and runs the
   smoke tests

A Docker image would not provide the same check. Linux containers still use
the Linux host kernel, and macOS is not available as a normal Docker image.
GitHub's hosted runners provide the real operating systems needed by these
tests.
