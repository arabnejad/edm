# Remote Integration Test Credentials

Every key and certificate in this directory is public test data. The remote
integration suite uses them only for the temporary Docker and SSH containers
created by `make remote-integration-test`.

Do not copy these credentials to a real Docker daemon or SSH server. Anyone
can read the private keys from the repository.

To replace all fixture files, run:

```bash
tests/integration_tests/remote/generate_remote_test_credentials.sh --force
```

The script creates the CA key in a temporary directory and removes it after
signing the server and client certificates. Keeping the CA key out of the
repository prevents the committed CA from being used to issue more
certificates.
