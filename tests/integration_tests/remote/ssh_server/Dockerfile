FROM docker:29.1.3-cli

# OpenSSH provides the transport while the Docker CLI forwards each SDK request.
# Password login stays disabled; passwd only unlocks public-key authentication.
RUN apk add --no-cache openssh-server \
    && adduser -D -s /bin/sh docker-user \
    && passwd -d docker-user \
    && mkdir -p /home/docker-user/.ssh /run/sshd

# A fixed host key makes the temporary server verifiable through known_hosts.
COPY fixtures/ssh/host-key /etc/ssh/ssh_host_ed25519_key
COPY fixtures/ssh/host-key.pub /etc/ssh/ssh_host_ed25519_key.pub
COPY fixtures/ssh/client-key.pub /tmp/client-key.pub
COPY ssh_server/sshd_config /etc/ssh/sshd_config

# The public test key can only proxy Docker traffic to the isolated dind service.
RUN { \
      printf '%s' 'command="/usr/local/bin/docker --host tcp://ssh-docker-daemon:2375 system dial-stdio",no-agent-forwarding,no-port-forwarding,no-pty,no-user-rc,no-X11-forwarding '; \
      cat /tmp/client-key.pub; \
    } > /home/docker-user/.ssh/authorized_keys \
    && rm /tmp/client-key.pub \
    && chown -R docker-user:docker-user /home/docker-user/.ssh \
    && chmod 0700 /home/docker-user/.ssh \
    && chmod 0600 /home/docker-user/.ssh/authorized_keys \
       /etc/ssh/ssh_host_ed25519_key \
    && chmod 0644 /etc/ssh/ssh_host_ed25519_key.pub

# Logging to stderr keeps connection failures visible in Compose and CI logs.
ENTRYPOINT ["/usr/sbin/sshd"]
CMD ["-D", "-e", "-f", "/etc/ssh/sshd_config"]
