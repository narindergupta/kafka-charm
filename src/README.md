# Description
Kafka is a high-performance, scalable, distributed messaging system.
This charm provides version 2.2 of the Kafka application from Apache.

# Overview
Apache Kafka is an open-source message broker project developed by the Apache
Software Foundation written in Scala. The project aims to provide a unified,
high-throughput, low-latency platform for handling real-time data feeds. Learn
more at kafka.apache.org.

This charm deploys version 2.2 of the Kafka component.

# Deploying
This charm requires Juju 2.7 or greater. If Juju is not yet set up, please
follow the getting-started instructions prior to deploying this charm.

Kafka requires the Zookeeper distributed coordination service. Deploy and
relate them as follows:

    juju deploy kafka
    juju deploy zookeeper
    juju deploy easyrsa
    juju add-relation kafka zookeeper
    juju add-relation kafka easyrsa

# Network-Restricted Environments

Charms can be deployed in environments with limited network access. To deploy
in this environment, configure a Juju model with appropriate proxy and/or
mirror options. See Configuring Models for more information.

# Using
Once deployed, there are a number of actions available in this charm.

List the zookeeper servers that our kafka brokers
are connected to. The following will list <ip>:<port> information for each
zookeeper unit in the environment (e.g.: 10.0.3.221:2181).

    juju run-action kafka/0 list-zks
    juju show-action-output <id>  # <-- id from above command
    
Create a Kafka topic with:

    juju run-action kafka/0 create-topic topic=<topic_name> \
     partitions=<#> replication=<#>
    juju show-action-output <id>  # <-- id from above command

List topics with:

    juju run-action kafka/0 list-topics
    juju show-action-output <id>  # <-- id from above command

Write to a topic with:

    juju run-action kafka/0 write-topic topic=<topic_name> data=<data>
    juju show-action-output <id>  # <-- id from above command
Read from a topic with:

    juju run-action kafka/0 read-topic topic=<topic_name> partition=<#>
    juju show-action-output <id>  # <-- id from above command
    juju run-action kafka/0 perf-test topic=one messages=10000 recordsize=10

# Verifying Status
Kafka charms provide extended status reporting to indicate when they
are ready:

    juju status
This is particularly useful when combined with watch to track the on-going
progress of the deployment:

    watch -n 2 juju status
The message column will provide information about a given unit's state.
This charm is ready for use once the status message indicates that it is
ready.

# Smoke Test
This charm provides a smoke-test action that can be used to verify the
application is functioning as expected. The test will verify connectivity
between Kafka and Zookeeper, and will test creation and listing of Kafka
topics. Run the action as follows:

    juju run-action --wait kafka/0 smoke-test
Watch the progress of the smoke test actions with:

# Performance Test
This charm provides a perf-test action that can be used to run the
application performance. The test will create the topic and run the
performance test and log all the data in kafka juju log files.
Run the action as follows:

    juju run-action kafka/0 perf-test topic=one messages=10000 recordsize=10
    juju debug-log --include kafka/0 would print the test metrics as well.

# Scaling
Expanding a cluster with many brokers is as easy as adding more Kafka units.
Expanding cluster does not make any effect on the curernt topics but any new
topic will be distributed on new kafka cluster machine.

    juju add-unit kafka
After adding additional brokers, topics may be created with
replication up to the number of ready units. For example, if there are two
ready units, create a replicated topic as follows:

    juju run-action kafka/0 create-topic topic=my-replicated-topic \
         partitions=1 replication=2
Query the description of the recently created topic:

    juju run --unit kafka/0 'kafka-topics --describe \
        --topic my-replicated-topic --zookeeper <zookeeperip>:2181'
    Topic: my-replicated-topic PartitionCount:1 ReplicationFactor:2 Configs:
    Topic: my-replicated-topic Partition: 0 Leader: 2 Replicas: 2,0 Isr: 2,0

# Connecting External Clients
By default, this charm does not expose Kafka outside of the provider's network.
To allow external clients to connect to Kafka, first expose the service:

    juju expose kafka
Next, ensure the external client can resolve the short hostname of the kafka
unit. A simple way to do this is to add an /etc/hosts entry on the external
kafka client machine. Gather the needed info from juju:

    $ juju run --unit kafka/0 'hostname -s' 
    kafka-0
    $ juju status --format=yaml kafka/0 | grep public-address
    public-address: 40.784.149.135
Update /etc/hosts on the external kafka client:

    $ echo "40.784.149.135 kafka-0" | sudo tee -a /etc/hosts
The external kafka client should now be able to access Kafka by using
kafka-0:9092 as the broker.

##Network Spaces
In some network environments, kafka may need to be restricted to
listen for incoming connections on a specific ingress interface
(e.g.: for security reasons). To do so, kafka charm binds kafka with a
seperate space specifying a ingress address.

Below juju command will give you the ip address where kafka binds to for
ingreee address

    juju run --unit kafka/1 "network-get --ingress-address --format yaml listener"
