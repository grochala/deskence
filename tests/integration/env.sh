# Source to use the integration harness with a scratch location.
export DESKENCE_TEST_DIR=${DESKENCE_TEST_DIR:-${TMPDIR:-/tmp}/deskence-test}
export DESKENCE_RUNTIME_DIR=${DESKENCE_RUNTIME_DIR:-${TMPDIR:-/tmp}/deskence-rt-$UID}
H=./tests/integration/session.sh
