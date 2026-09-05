FROM docker:29.1.3-dind

# The dind entrypoint uses these files instead of creating a new CA at startup.
COPY fixtures/tls/ca.pem /certs/server/ca.pem
COPY fixtures/tls/server-cert.pem /certs/server/cert.pem
COPY fixtures/tls/server-key.pem /certs/server/key.pem

# Keep the private key readable only by dockerd inside the test container.
RUN chmod 0444 /certs/server/ca.pem /certs/server/cert.pem \
    && chmod 0400 /certs/server/key.pem
