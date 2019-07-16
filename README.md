# kafka-charm

This charm will use deb package from Ubuntu private PPA.

# Building

    cd src
    charm build

Will build the Kafka charm, and then the charm in `/tmp/charm-builds`.

# Operating

This charm require the private ppa configuration. It relates to zookeeper and
scales horizontally by adding units.

    juju deploy /tmp/charm-builds/kafka
    juju deploy zookeeper
    juju relate kafka zookeeper

# Notes

The Kafka charm requires at least 4GB of memory.

# Details

Much of the charm implementation is borrowed from the Apache kafka
charm, but it's been heavily simplified and pared down. Jinja templating is
used instead of Puppet, and a few helper functions that were imported from
libraries are inlined.

---
