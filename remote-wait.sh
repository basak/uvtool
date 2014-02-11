#!/bin/sh
set -e

# Wait for runlevel 2
while [ "$(runlevel|awk '{print $2}')" != 2 ]; do sleep $UVTOOL_WAIT_INTERVAL; done

# Wait for cloud-init's signal
while [ ! -e /var/lib/cloud/instance/boot-finished ]; do sleep $UVTOOL_WAIT_INTERVAL; done
