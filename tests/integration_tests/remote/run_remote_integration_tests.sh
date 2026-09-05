#!/usr/bin/env bash

set -euo pipefail

# =============================================================================
# Check prerequisites and test fixtures
# =============================================================================

remote_test_directory="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
project_root="$(cd "${remote_test_directory}/../../.." && pwd)"
compose_file="${remote_test_directory}/compose.yaml"
fixture_directory="${remote_test_directory}/fixtures"
python_executable="${PYTHON:-python}"
remote_test_container_image="${EDM_REMOTE_INTEGRATION_TEST_IMAGE:-alpine:3.20}"

required_commands=(docker "${python_executable}")
for command_name in "${required_commands[@]}"; do
    if ! command -v "${command_name}" >/dev/null 2>&1; then
        printf 'Required command not found: %s\n' "${command_name}" >&2
        exit 1
    fi
done

required_fixture_files=(
    "${fixture_directory}/tls/ca.pem"
    "${fixture_directory}/tls/server-cert.pem"
    "${fixture_directory}/tls/server-key.pem"
    "${fixture_directory}/tls/client-cert.pem"
    "${fixture_directory}/tls/client-key.pem"
    "${fixture_directory}/ssh/client-key"
    "${fixture_directory}/ssh/client-key.pub"
    "${fixture_directory}/ssh/host-key"
    "${fixture_directory}/ssh/host-key.pub"
)
for fixture_file in "${required_fixture_files[@]}"; do
    if [[ ! -f "${fixture_file}" ]]; then
        printf 'Remote test fixture not found: %s\n' "${fixture_file}" >&2
        printf 'Run tests/integration_tests/remote/generate_remote_test_credentials.sh\n' >&2
        exit 1
    fi
done

# The remote fixtures need a local daemon for their temporary dind containers.
docker --context default info >/dev/null
docker compose version >/dev/null

# =============================================================================
# Start the temporary Compose services and register their cleanup
# =============================================================================

runtime_directory="$(mktemp -d)"
compose_project_name="edm-remote-integration-${$}"
compose_command=(
    docker --context default compose
    --project-name "${compose_project_name}"
    --file "${compose_file}"
)

cleanup() {
    exit_status=$?
    set +e
    if [[ ${exit_status} -ne 0 ]]; then
        printf '\nRemote test service logs:\n' >&2
        "${compose_command[@]}" logs --no-color --tail 200 >&2
    fi
    "${compose_command[@]}" down \
        --volumes \
        --remove-orphans \
        --rmi local \
        >/dev/null 2>&1
    rm -rf "${runtime_directory}"
    trap - EXIT
    exit "${exit_status}"
}
trap cleanup EXIT

"${compose_command[@]}" up \
    --build \
    --detach \
    --wait \
    --wait-timeout 120

# =============================================================================
# Create isolated Docker and SSH client configuration
# =============================================================================

tls_published_address="$("${compose_command[@]}" port tls-docker-daemon 2376)"
ssh_published_address="$("${compose_command[@]}" port ssh-docker-proxy 22)"
tls_port="${tls_published_address##*:}"
ssh_port="${ssh_published_address##*:}"

test_home_directory="${runtime_directory}/home"
docker_config_directory="${runtime_directory}/docker-config"
mkdir -p "${test_home_directory}/.ssh" "${docker_config_directory}"

# Keep the developer's Docker contexts and SSH files out of this test run.
printf '{"currentContext":"default"}\n' \
    > "${docker_config_directory}/config.json"
cp "${fixture_directory}/ssh/client-key" \
    "${test_home_directory}/.ssh/client-key"
chmod 0600 "${test_home_directory}/.ssh/client-key"

cat > "${test_home_directory}/.ssh/config" <<EOF
Host 127.0.0.1
    IdentityFile ${test_home_directory}/.ssh/client-key
    IdentitiesOnly yes
EOF
chmod 0600 "${test_home_directory}/.ssh/config"

ssh_host_public_key="$(cut -d ' ' -f 1,2 \
    "${fixture_directory}/ssh/host-key.pub")"
{
    # Paramiko uses the first form for port 22 and the second for other ports.
    printf '127.0.0.1 %s\n' "${ssh_host_public_key}"
    printf '[127.0.0.1]:%s %s\n' "${ssh_port}" "${ssh_host_public_key}"
} > "${test_home_directory}/.ssh/known_hosts"
chmod 0600 "${test_home_directory}/.ssh/known_hosts"

# =============================================================================
# Create temporary Docker contexts for the two remote connections
# =============================================================================

tls_context_name="edm-remote-tls-test"
ssh_context_name="edm-remote-ssh-test"

docker --config "${docker_config_directory}" context create \
    "${tls_context_name}" \
    --description "EDM TLS integration test" \
    --docker "host=tcp://127.0.0.1:${tls_port},ca=${fixture_directory}/tls/ca.pem,cert=${fixture_directory}/tls/client-cert.pem,key=${fixture_directory}/tls/client-key.pem"

docker --config "${docker_config_directory}" context create \
    "${ssh_context_name}" \
    --description "EDM SSH integration test" \
    --docker "host=ssh://docker-user@127.0.0.1:${ssh_port}"

# =============================================================================
# Run the tests through both remote Docker contexts
# =============================================================================

cd "${project_root}"
env \
    -u DOCKER_HOST \
    -u DOCKER_CONTEXT \
    -u DOCKER_TLS_VERIFY \
    -u DOCKER_CERT_PATH \
    -u SSH_AUTH_SOCK \
    HOME="${test_home_directory}" \
    DOCKER_CONFIG="${docker_config_directory}" \
    EDM_REMOTE_TLS_CONTEXT_NAME="${tls_context_name}" \
    EDM_REMOTE_SSH_CONTEXT_NAME="${ssh_context_name}" \
    EDM_REMOTE_INTEGRATION_TEST_IMAGE="${remote_test_container_image}" \
    "${python_executable}" -m pytest \
        --no-cov \
        -m remote_integration \
        tests/integration_tests/remote
