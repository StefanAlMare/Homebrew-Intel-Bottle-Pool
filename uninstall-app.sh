#!/bin/sh
set -eu
# The upstream uninstaller targets production app/data. Never ship that behavior
# in this local test copy. No deletion, launchctl or config mutation is performed.
echo "Automatic uninstall is disabled for the 0.3.6 test copy." >&2
echo "Keep the production app and all queues. Remove only the separate test app manually if needed." >&2
exit 2
