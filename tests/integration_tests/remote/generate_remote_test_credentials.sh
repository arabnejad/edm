#!/usr/bin/env bash

set -euo pipefail

# =============================================================================
# Check prerequisites and arguments
# =============================================================================

remote_test_directory="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
fixture_directory="${remote_test_directory}/fixtures"
tls_fixture_directory="${fixture_directory}/tls"
ssh_fixture_directory="${fixture_directory}/ssh"

required_commands=(openssl ssh-keygen)
for command_name in "${required_commands[@]}"; do
    if ! command -v "${command_name}" >/dev/null 2>&1; then
        printf 'Required command not found: %s\n' "${command_name}" >&2
        exit 1
    fi
done

if [[ $# -gt 1 || ( $# -eq 1 && "$1" != "--force" ) ]]; then
    printf 'Usage: %s [--force]\n' "$0" >&2
    exit 1
fi

credential_fixture_files=(
    "${tls_fixture_directory}/ca.pem"
    "${tls_fixture_directory}/server-cert.pem"
    "${tls_fixture_directory}/server-key.pem"
    "${tls_fixture_directory}/client-cert.pem"
    "${tls_fixture_directory}/client-key.pem"
    "${ssh_fixture_directory}/client-key"
    "${ssh_fixture_directory}/client-key.pub"
    "${ssh_fixture_directory}/host-key"
    "${ssh_fixture_directory}/host-key.pub"
)

any_credential_fixture_exists=false
for credential_fixture_file in "${credential_fixture_files[@]}"; do
    if [[ -e "${credential_fixture_file}" ]]; then
        any_credential_fixture_exists=true
        break
    fi
done

if [[ "${any_credential_fixture_exists}" == true && "${1:-}" != "--force" ]]; then
    printf 'Test credentials already exist. Pass --force to replace them.\n' >&2
    exit 1
fi

# =============================================================================
# Build the replacement credentials in a temporary directory
# =============================================================================

temporary_directory="$(mktemp -d)"
trap 'rm -rf "${temporary_directory}"' EXIT

generated_tls_fixture_directory="${temporary_directory}/tls"
generated_ssh_fixture_directory="${temporary_directory}/ssh"
mkdir -p \
    "${generated_tls_fixture_directory}" \
    "${generated_ssh_fixture_directory}"

# =============================================================================
# Generate the TLS CA, server certificate, and client certificate
# =============================================================================

ca_private_key="${temporary_directory}/ca-key.pem"
server_certificate_request="${temporary_directory}/server.csr"
client_certificate_request="${temporary_directory}/client.csr"

# No password option is passed to genrsa, so these test keys are unencrypted.
# The CA key is needed only while signing the fixture certificates.
openssl genrsa -out "${ca_private_key}" 4096
# -x509 creates the self-signed CA certificate, and -subj avoids a prompt.
# The CA lasts one year longer than the certificates it signs.
openssl req -new -x509 -sha256 -days 4015 \
    -key "${ca_private_key}" \
    -subj "/CN=EDM remote integration test CA" \
    -addext "basicConstraints=critical,CA:TRUE" \
    -addext "keyUsage=critical,keyCertSign,cRLSign" \
    -out "${generated_tls_fixture_directory}/ca.pem"

cat > "${temporary_directory}/server-extensions.cnf" <<'EOF'
[server_extensions]
basicConstraints = critical,CA:FALSE
keyUsage = critical,digitalSignature,keyEncipherment
extendedKeyUsage = serverAuth
subjectAltName = DNS:tls-docker-daemon,DNS:localhost,IP:127.0.0.1
EOF

# Create the server key and a certificate request without interactive prompts.
openssl genrsa -out "${generated_tls_fixture_directory}/server-key.pem" 2048
openssl req -new -sha256 \
    -key "${generated_tls_fixture_directory}/server-key.pem" \
    -subj "/CN=tls-docker-daemon" \
    -out "${server_certificate_request}"
# Sign the request with the test CA. Serial 1001 distinguishes it from the
# client certificate. The extension file limits it to server authentication
# and lists the names used to reach it in the tests.
openssl x509 -req -sha256 -days 3650 \
    -in "${server_certificate_request}" \
    -CA "${generated_tls_fixture_directory}/ca.pem" \
    -CAkey "${ca_private_key}" \
    -set_serial 1001 \
    -extfile "${temporary_directory}/server-extensions.cnf" \
    -extensions server_extensions \
    -out "${generated_tls_fixture_directory}/server-cert.pem"

cat > "${temporary_directory}/client-extensions.cnf" <<'EOF'
[client_extensions]
basicConstraints = critical,CA:FALSE
keyUsage = critical,digitalSignature
extendedKeyUsage = clientAuth
EOF

# The client key and certificate request are also created without a prompt.
openssl genrsa -out "${generated_tls_fixture_directory}/client-key.pem" 2048
openssl req -new -sha256 \
    -key "${generated_tls_fixture_directory}/client-key.pem" \
    -subj "/CN=EDM remote integration test client" \
    -out "${client_certificate_request}"
# Serial 1002 distinguishes this certificate from the server certificate. Its
# extension file marks it for client authentication.
openssl x509 -req -sha256 -days 3650 \
    -in "${client_certificate_request}" \
    -CA "${generated_tls_fixture_directory}/ca.pem" \
    -CAkey "${ca_private_key}" \
    -set_serial 1002 \
    -extfile "${temporary_directory}/client-extensions.cnf" \
    -extensions client_extensions \
    -out "${generated_tls_fixture_directory}/client-cert.pem"

# Check that the CA can verify both signed certificates before keeping them.
openssl verify -CAfile "${generated_tls_fixture_directory}/ca.pem" \
    "${generated_tls_fixture_directory}/server-cert.pem" \
    "${generated_tls_fixture_directory}/client-cert.pem"

# =============================================================================
# Generate the SSH client and host key pairs
# =============================================================================

# -N "" sets an empty passphrase so CI can use these test keys unattended.
# -q hides progress, -t selects Ed25519, -C adds a label to the public key, and
# -f chooses the output file.
ssh-keygen -q -t ed25519 -N "" \
    -C "edm-remote-integration-client" \
    -f "${generated_ssh_fixture_directory}/client-key"
ssh-keygen -q -t ed25519 -N "" \
    -C "edm-remote-integration-host" \
    -f "${generated_ssh_fixture_directory}/host-key"

# =============================================================================
# Protect, inspect, and install the completed fixture set
# =============================================================================

# Only the current user should be able to read the generated private keys.
chmod 0600 \
    "${generated_tls_fixture_directory}/server-key.pem" \
    "${generated_tls_fixture_directory}/client-key.pem" \
    "${generated_ssh_fixture_directory}/client-key" \
    "${generated_ssh_fixture_directory}/host-key"

printf '\nTLS certificate dates:\n'
openssl x509 -in "${generated_tls_fixture_directory}/ca.pem" -noout -dates
openssl x509 -in "${generated_tls_fixture_directory}/server-cert.pem" -noout -dates
openssl x509 -in "${generated_tls_fixture_directory}/client-cert.pem" -noout -dates
printf '\nSSH key fingerprints:\n'
ssh-keygen -lf "${generated_ssh_fixture_directory}/client-key.pub"
ssh-keygen -lf "${generated_ssh_fixture_directory}/host-key.pub"

# Replace the old set only after every new key and certificate has passed its check.
rm -rf "${tls_fixture_directory}" "${ssh_fixture_directory}"
mv "${generated_tls_fixture_directory}" "${tls_fixture_directory}"
mv "${generated_ssh_fixture_directory}" "${ssh_fixture_directory}"
printf '\nRemote integration test credentials have been regenerated.\n'
