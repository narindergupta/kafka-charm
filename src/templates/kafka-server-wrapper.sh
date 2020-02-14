#!/bin/bash

set -eu

if [ ! -f /etc/kafka/server.properties ]; then
        echo "configuration file /etc/kafka/server.properties does not exist."
        exit 1
fi

export PATH=/usr/lib/jvm/default-java/bin:$PATH

if [ -e "/etc/kafka/broker.env" ]; then
    . /etc/kafka/broker.env
fi

/usr/lib/kafka/bin/kafka-server-start.sh /etc/kafka/server.properties
