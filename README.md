# Easy Docker Manager

<img src="docs/assets/logo.png" alt="Easy Docker Manager logo" width="200">

[![PyPI](https://img.shields.io/pypi/v/easy-docker-manager?logo=pypi&logoColor=white&cacheSeconds=300)](https://pypi.org/project/easy-docker-manager/)
[![Python](https://img.shields.io/pypi/pyversions/easy-docker-manager?logo=python&logoColor=white)](https://pypi.org/project/easy-docker-manager/)
[![Quality](https://github.com/arabnejad/edm/actions/workflows/quality.yml/badge.svg?branch=main)](https://github.com/arabnejad/edm/actions/workflows/quality.yml)
[![Package](https://github.com/arabnejad/edm/actions/workflows/package.yml/badge.svg?branch=main)](https://github.com/arabnejad/edm/actions/workflows/package.yml)
[![Security](https://github.com/arabnejad/edm/actions/workflows/security.yml/badge.svg?branch=main)](https://github.com/arabnejad/edm/actions/workflows/security.yml)
[![License: MIT](https://custom-icon-badges.demolab.com/github/license/arabnejad/edm?logo=law&logoColor=white)](https://github.com/arabnejad/edm/blob/main/LICENSE)

[![Open issues](https://custom-icon-badges.demolab.com/github/issues-raw/arabnejad/edm?logo=issue-opened&logoColor=white)](https://github.com/arabnejad/edm/issues)
[![Open pull requests](https://custom-icon-badges.demolab.com/github/issues-pr-raw/arabnejad/edm?logo=git-pull-request&logoColor=white)](https://github.com/arabnejad/edm/pulls)

[![Black](https://img.shields.io/badge/code%20style-black-000000?logo=black&logoColor=white)](https://github.com/psf/black)
[![Ruff](https://img.shields.io/badge/linter-ruff-D7FF64?logo=ruff&logoColor=black)](https://docs.astral.sh/ruff/)
[![mypy](https://img.shields.io/badge/type%20checked-mypy-2A6DB2?logo=python&logoColor=white)](https://mypy-lang.org/)
[![CodeQL](https://github.com/arabnejad/edm/actions/workflows/github-code-scanning/codeql/badge.svg?branch=main)](https://github.com/arabnejad/edm/actions/workflows/github-code-scanning/codeql)

Easy Docker Manager (EDM) lets you inspect Docker containers from a
keyboard-driven terminal interface. It uses Urwid for the screen and the
Docker Python SDK to read container data.

With EDM, you can view:

- a list of running containers
- recent logs with automatic updates
- container environment variables
- a readable summary of Docker inspection data
- current CPU, memory, network, disk, and process statistics
- the process list returned by Docker top
- Stop and Restart actions for running containers
- live filtering and sorting of the running-container list
- a separate search query for each container tab
- export of the active tab to a local text file
- a local JSON configuration file

## Demo

![Easy Docker Manager demo](docs/assets/edm-demo.gif)

## Requirements

- Python 3.9 or newer
- Docker installed and running
- permission to access the Docker daemon you want to use
- a terminal window of at least 120 columns by 30 rows

EDM supports local Docker sockets, Windows named pipes, SSH contexts, and TCP
contexts secured with verified TLS. Plain TCP connections and contexts that
skip server verification are listed but cannot be selected.

> [!WARNING]
> EDM needs access to the selected Docker daemon. This is highly privileged
> access, whether the daemon is local or remote. On Linux, membership in the
> `docker` group grants root-level privileges. Give Docker access only to
> trusted users, and never make the Docker socket world-writable. See Docker's
> [Linux post-installation guidance](https://docs.docker.com/engine/install/linux-postinstall/)
> for supported access options.

## Installation

For normal use, install EDM with `pipx`:

```bash
pipx install easy-docker-manager
```

`pipx` keeps EDM in its own environment and makes the `edm` command available
from your terminal.

You can also install EDM with `pip`. Using a virtual environment keeps it
separate from other Python packages:

```bash
python -m venv .venv
```

Activate the environment on Linux or macOS:

```bash
source .venv/bin/activate
```

Activate it in Windows PowerShell:

```powershell
.venv\Scripts\Activate.ps1
```

Or activate it in Windows Command Prompt:

```bat
.venv\Scripts\activate.bat
```

Then install the package from PyPI:

```bash
python -m pip install easy-docker-manager
```

For work on the source code, follow the
[development setup](DEVELOPMENT_GUIDE.md#development-setup).

## Running EDM

Run the installed command:

```bash
edm
```

EDM checks the terminal size before it starts. If the window is smaller than
120 columns by 30 rows, EDM prints the current size and exits. Resize the
terminal and run the command again.

Show the available command options or installed version, or start EDM without
terminal colors:

```bash
edm --help
edm --version
edm --diagnostics
edm --no-color
```

You can also run the Python module directly:

```bash
python -m easy_docker_manager
```

## Remote Docker Over SSH

EDM uses the contexts already configured for the Docker command line. It does
not keep its own server list or change the context used by other terminals.

Before creating a context, check that SSH works without asking for a password
and that the remote user can reach Docker without `sudo`:

```bash
ssh docker-user@remote-server-address
ssh docker-user@remote-server-address docker ps
```

Use an SSH key or `ssh-agent` for authentication. Connect with `ssh` once before
opening EDM so the server's host key is present in `~/.ssh/known_hosts`.

Create a Docker context on the computer where EDM runs:

```bash
docker context create remote-server-context \
  --description "Remote Docker server" \
  --docker "host=ssh://docker-user@remote-server-address"
```

In this example, `remote-server-context` is the context name shown in Docker
and EDM. Replace `docker-user` with the SSH username and
`remote-server-address` with the remote server's hostname or IP address.

Include the port in the SSH address when the server does not use port 22:

```bash
docker context create remote-server-context \
  --docker "host=ssh://docker-user@remote-server-address:2222"
```

Test the context before opening EDM:

```bash
docker --context remote-server-context ps
```

Inside EDM, press `c` or `C`, select `remote-server-context`, and press
`Enter`. EDM checks the connection in the background. If it succeeds, EDM
clears the old container data and loads running containers from the selected
context. If it fails, the current connection stays active and the popup shows
the reason.

Opening the popup does not connect to every saved server. EDM checks a remote
connection only after you select it and press `Enter`. EDM cannot ask for or
store an SSH password, so the connection must use a working key or `ssh-agent`.

## Remote Docker Over TLS

SSH and TLS are two separate ways to connect EDM to a remote Docker daemon:

| SSH connection | TLS connection |
| --- | --- |
| Sends Docker requests through an SSH connection | Sends Docker requests directly to the daemon over an encrypted TCP connection |
| Requires a remote SSH user and a working SSH key or `ssh-agent` | Requires a CA certificate, client certificate, and private key |
| Uses the server entry in `~/.ssh/known_hosts` to check the server's identity | Uses the CA certificate to check the Docker server's identity |
| Does not require the Docker daemon to listen on a TCP port | Requires the Docker daemon to accept TLS connections, usually on port `2376` |

TLS does not use SSH, so it does not require passwordless SSH or an SSH account
on the remote server. The TLS certificates provide three protections:

- traffic between EDM and Docker is encrypted;
- the CA certificate confirms that EDM reached the expected Docker server;
- the client certificate and private key prove that EDM is allowed to connect.

This is often called mutual TLS because both sides prove their identity. Treat
the client certificate and private key as sensitive files: anyone who can use
them may have full control of the remote Docker daemon.

Creating a Docker context does not configure the remote server. It does not
contact the server, ask for a password, or copy certificate files to it. The
remote Docker daemon must already be listening for verified TLS connections.

See [Connect EDM to Remote Docker with TLS](docs/remote-docker-tls.md) for the
complete server and client setup.

After the server is ready, create the context on the computer where EDM runs:

```bash
docker context create remote-tls-context \
  --description "Remote Docker server over TLS" \
  --docker "host=tcp://remote-server-address:2376,ca=/path/to/ca.pem,cert=/path/to/cert.pem,key=/path/to/key.pem"
```

Replace the context name, server address, and certificate paths with your own
values. Test the context before opening EDM:

```bash
docker --context remote-tls-context version
```

Inside EDM, press `c` or `C`, select `remote-tls-context`, and press `Enter`.
Docker's context configuration supplies the certificates; EDM does not add
certificate paths to `config.json`.

EDM accepts the TCP context only when all three certificate files are present
and the server certificate is verified. A context created with
`skip-tls-verify` remains unavailable.

## Keyboard Controls

| Key | Action |
| --- | --- |
| `q` | Quit EDM from the normal screen |
| `h` or `H` | Open application help and Docker diagnostics |
| `p` or `P` | Open the settings editor |
| `c` or `C` | Open Docker context selection |
| `Up` / `Down` | Move through containers or detail lines |
| `Enter` | Move keyboard focus to the detail panel |
| `Esc` | Return keyboard focus to the container list |
| `[` | Open the previous detail tab |
| `]` | Open the next detail tab |
| `/` | Start editing the search for the current tab |
| `f` | Start editing the container filter while the container panel is active |
| `s` | Open container sorting while the container panel is active |
| `a` or `A` | Open actions for the selected running container |
| `e` | Export the active tab while the detail panel is active |
| `Page Up` / `Page Down` | Move through the detail panel one page at a time |
| `Home` / `End` | Select the first or last detail line |

While entering a search, press `Enter` to keep the query and return to detail
navigation. Press `Esc` to keep the query and return to the container list.

## Help And Diagnostics

Press `h` or `H` to open the keyboard shortcut list and diagnostics without
leaving EDM. Application versions and file paths appear immediately. Docker
details are loaded in the background, so an unavailable daemon does not stop
keyboard input. Press `Esc` to close the popup. The Docker check runs again
each time the popup opens. The title panel also shows the installed EDM
version.

Use the command-line report when the terminal interface cannot start:

```bash
edm --diagnostics
```

The report includes the EDM, Python, Docker SDK, and Docker daemon versions. It
also shows the active Docker context, config path, application log path, Docker
API version, platform, and connection result. A failed Docker check prints its
error and exits with status `1`; a successful check exits with status `0`.
This command does not create or rewrite `config.json`.

## Container Actions

Select a running container and press `a` or `A`. Choose **Restart** or **Stop**
with `Up` and `Down`, then press `Enter`. EDM asks for confirmation before it
sends the request to Docker. Press `Esc` to close the popup without making a
change.

The Docker request runs in the background. After it succeeds, EDM reloads the
running-container list. A stopped container disappears from the list because
EDM does not show stopped containers yet.

Restart uses the existing container and its current Docker configuration. It
does not reread a Compose file or recreate a Compose service.

## Container Filtering

Press `f` while the container panel is active, then type part of a container
name, image name, status, Compose project, or Compose service. Matching ignores
letter case and updates the list as you type. It uses the container data
already loaded in EDM and does not send another request to Docker.

```text
* localhost (active)
────────────────────────
 f  Filter: off
 s  Sort: Docker order
────────────────────────
> container-one (running)
  container-two (running)
```

Use `Backspace` to remove the last character. Press `Enter` to keep the edited
filter, or press `Esc` to restore the filter that was active before you pressed
`f`. Other navigation and shortcut keys are disabled until editing ends. Every
printable key, including `q`, becomes part of the query.

The filter and match count are shown below `localhost (active)`, next to the
`f` shortcut. The active sort appears on the following line. EDM reapplies the
filter and sort after each container-list refresh. If the selected container
no longer matches, the first matching container is selected. Filtering only
hides list entries; cached tab data for hidden running containers is kept.

## Docker Compose Grouping

Docker Compose grouping is automatic. Containers with the same
`com.docker.compose.project` label appear together under the project name:

```text
accounts (2)
  > accounts-api-1 (running)
    accounts-worker-1 (running)
────────────────────────
monitoring (1)
    monitoring-grafana-1 (running)
────────────────────────
    cadvisor (running)
```

Containers started without Docker Compose stay at the end of the list. They
are shown as normal container rows without a `Standalone` heading.

Project headings and separator lines are not selectable. `Up` and `Down` move
directly between containers. EDM keeps the current container selected after a
list refresh when that container is still running and still matches the filter.

## Container Sorting

Press `s` while the container panel is active to open this menu:

```text
Sort Containers

  Docker order
> Name
  Image
  Status
  Creation time

Direction: Ascending

Up/Down Field   Left/Right Direction
Enter Apply     Esc Cancel
```

Use `Up` and `Down` to choose a field. Use `Left` for ascending order and
`Right` for descending order. `Enter` applies the choice, while `Esc` closes
the menu without changing the list. The active sort is shown above the
container list, directly below the active filter.

Applying a sort does not change the selected container. The sort stays active
after the container list refreshes. Compose projects stay in name order. Docker
order restores the order returned by Docker inside each project and among the
containers without a Compose project at the end.

EDM currently shows running containers only, so they usually have the same
status. For this reason, sorting by Status may not visibly change the list.

## Exporting Tab Content

Press `e` while the detail panel is active to export the selected container's
Logs, Env, Config, Stats, or Top tab. The popup lets you edit the destination
path and choose one of these scopes:

- **Current view** exports the lines currently shown after a Logs filter. Env,
  Config, Stats, and Top searches highlight text without hiding lines, so their
  current view contains all loaded text.
- **Full loaded tab** exports all text currently held in EDM's cache. It does
  not request more data or older logs from Docker.

The suggested path starts in the directory where you launched EDM. Logs use a
`.log` extension; the other tabs use `.txt`. Relative paths are also resolved
from that launch directory. When the path is inside your home directory, the
File field shows the home directory as `~` to keep the path shorter.

While File is selected, printable keys, including `q` and `Q`, edit the path.
Use `Left` and `Right` to move its cursor, `Home` or `End` to jump to either
end, and `Backspace` or `Delete` to remove characters. Use `Up`, `Down`, or
`Tab` to move between File and Scope.

Exports may contain passwords, tokens, URLs, command arguments, or other
sensitive values. EDM shows a warning before every export and writes the text
without hiding values. Review exported files before sharing them. EDM never
replaces an existing file without asking for confirmation.

## Detail Tabs

| Tab | Contents |
| --- | --- |
| Logs | Recent container logs followed by new log output |
| Env | Configured environment variables and their values |
| Config | Selected container and image inspection data |
| Stats | CPU, memory, network, block I/O, and process usage from Docker |
| Top | Processes reported by Docker top |

Stats reloads every two seconds by default while that tab is visible. Network
and block I/O rates need two samples, so the first sample shows `N/A` for those
rates. Docker does not report every counter on every operating system or cgroup
version; unavailable values also appear as `N/A`.

Each container and tab keeps its own search query:

- Logs treats the query as a case-insensitive regular expression and hides
  lines that do not match.
- Env, Config, Stats, and Top use case-insensitive plain-text search. Matches are
  highlighted, but no lines are removed.
- An invalid Logs regular expression leaves the log text visible.
- Log regular expressions are limited to 200 characters.

## Configuration

Press `p` or `P` to edit the saved settings without leaving EDM. Use `Up` and
`Down` to select a field. Press `Enter` to edit a number, then press `Enter`
again to accept it. `Left` and `Right` change Boolean values and the
application log level.

Press `s` to save, `d` to load the default values into the form, or `Esc` to
close the popup without saving. When a number is being edited, the first
`Esc` cancels that edit and returns to the form. Loading defaults does not
change `config.json` until `s` is pressed.

Saved changes take effect after EDM restarts. The Docker client, worker pool,
cache, and terminal colors are created during startup, so EDM does not replace
them while it is running.

EDM uses `platformdirs` to place `config.json` in the correct user config
directory for the operating system. The file is stored in an `EDM` folder.
Typical locations are:

| Operating system | Typical path |
| --- | --- |
| Linux | `~/.config/EDM/config.json` |
| macOS | `~/Library/Application Support/EDM/config.json` |
| Windows | `%LOCALAPPDATA%\EDM\config.json` |

EDM creates this file on first use. On later starts, it keeps valid settings,
fills in missing defaults, removes unknown or invalid values, and writes the
cleaned configuration back to the file.

| Setting | Default | Purpose |
| --- | ---: | --- |
| `container_list_refresh_interval_seconds` | `2.0` | Seconds between running-container refreshes |
| `tab_refresh_interval` | `2.0` | Seconds between reloads of the visible Env, Config, Stats, or Top tab |
| `initial_log_tail_lines` | `100` | Number of recent lines loaded when Logs first opens |
| `max_log_lines` | `2000` | Maximum log lines kept for one container |
| `max_log_line_chars` | `4000` | Maximum characters kept from one log line (minimum `32`) |
| `tab_content_cache_max_entries` | `50` | Maximum number of cached container tabs |
| `tab_content_cache_max_bytes` | `25000000` | Maximum UTF-8 size of all cached tab text |
| `docker_request_timeout` | `10.0` | Docker SDK request timeout in seconds |
| `max_background_worker_threads` | `4` | Maximum number of background worker threads |
| `colors_enabled` | `true` | Use terminal colors; set to `false` for monochrome output |
| `application_log_level` | `"INFO"` | Minimum level written to EDM's application log |
| `application_log_to_stdout` | `false` | Also write EDM application messages to standard output |

`edm --no-color` disables colors for one run without changing `config.json`.

## Application Logs

EDM writes its own application messages to `edm.log` beside `config.json`.
This file contains EDM errors and diagnostic messages, not container logs. It
rotates at 5 MB and keeps three backup files.

Paramiko errors from remote SSH connections are written to the same file.
They are kept out of the terminal so they do not overwrite the EDM screen.

The application log level and stdout output can be changed in the settings
editor or `config.json`. These environment variables override saved values for
one run:

| Variable | Purpose |
| --- | --- |
| `EDM_LOG_FILE` | Write to a different log file |
| `EDM_LOG_LEVEL` | Set the level, such as `DEBUG` or `WARNING` |
| `EDM_LOG_STDOUT` | Also write logs to standard output when enabled |

`EDM_LOG_STDOUT` is disabled for `0`, `false`, `no`, or `off`. Other values
enable it. If EDM cannot create the log file, it prints a warning to the
terminal and continues to start.

## Development Checks

Run the normal formatting, linting, type, and source-security checks:

```bash
make check
```

Useful individual commands are:

```bash
make black
make black-check
make ruff
make ruff-fix
make mypy
make bandit
make test
make integration-test
make smoke-test
make pre-commit
make audit
make security
make package-check
```

`make audit` checks installed dependencies for known vulnerabilities. It needs
Python 3.10 or newer and network access, so it is not part of `make check`.

`make test` prints statement and branch coverage after the unit tests finish.
`make integration-test` starts a temporary Alpine container and checks container
listing, logs, environment variables, inspection data, and process information.
It requires access to a running local Docker daemon.
`make smoke-test` checks package imports, platform paths, notifier selection,
and basic startup on the current operating system.

GitHub Actions runs Black, Ruff, mypy, and Bandit once on Python 3.12. It runs
the unit tests on Python 3.9 through 3.14, runs the Docker integration tests on
Python 3.12, runs wheel smoke tests on Windows and macOS, and verifies the
minimum supported runtime dependency versions on Python 3.9. It also checks
dependencies and committed secrets, builds the source distribution and wheel,
and installs the wheel on every supported Python version. Dependabot checks
Python packages and GitHub Actions each week.

Workflow actions are pinned to full commit SHAs so CI always runs the exact
reviewed action code instead of a movable version tag. The comment beside each
SHA shows its release version, and Dependabot proposes SHA updates when newer
releases are available.

See [DEVELOPMENT_GUIDE.md](DEVELOPMENT_GUIDE.md) for the code structure,
runtime flow, and instructions for extending EDM.

## Contributing

Bug reports, feature ideas, and code contributions are welcome. Read
[CONTRIBUTING.md](CONTRIBUTING.md) before opening a pull request.

Please report security problems privately by following
[SECURITY.md](SECURITY.md). Do not include sensitive vulnerability details in
a public issue.

## License

Easy Docker Manager is available under the [MIT License](LICENSE).
