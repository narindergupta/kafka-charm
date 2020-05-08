# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License.  You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os, sys, stat
import socket
import json
import base64
import tempfile
from OpenSSL import crypto
from subprocess import check_call
from pathlib import Path
import charms.coordinator
from charms.layer.kafka import Kafka
from charms.layer.kafka import keystore_password, KAFKA_APP_DATA
from charms.layer import tls_client
from charmhelpers.core import hookenv, unitdata
from charms.reactive import (when, when_not, hook, when_file_changed,
                             remove_state, set_state, endpoint_from_flag,
                             set_flag, is_state)
from charms.reactive.helpers import data_changed
from charmhelpers.core.hookenv import log


@when_not('apt.installed.kafka')
def install_kafka():
    hookenv.status_set('blocked', 'waiting for installation of Kafka Package')

@when('apt.installed.kafka')
@when_not('zookeeper.joined')
def waiting_for_zookeeper():
    hookenv.status_set('blocked', 'waiting for relation to zookeeper')


@when('apt.installed.kafka', 'zookeeper.joined')
@when_not('kafka.started', 'zookeeper.ready')
def waiting_for_zookeeper_ready(zk):
    hookenv.status_set('waiting', 'waiting for zookeeper to become ready')


@when_not('kafka.storage.logs.attached')
@when('apt.installed.kafka')
def waiting_for_storage_attach():
    if hookenv.config()['log_dir']:
        # It seems directory has been already mounted to unit.
        set_state('kafka.storage.logs.attached')
    else:
        hookenv.status_set('waiting', 'waiting for storage attachment')


@when_not('kafka.ca.keystore.saved',
        'kafka.server.keystore.saved')
@when('apt.installed.kafka')
def waiting_for_certificates():
    config = hookenv.config()
    if config['ssl_cert']:
        set_state('certificates.available')
    else:
        hookenv.status_set('waiting', 'Waiting relation to certificate authority.')


@when('config.changed.ssl_key_password', 'kafka.started')
def change_ssl_key():
    kafka = Kafka()
    config = hookenv.config()
    password = keystore_password()
    new_password = config['ssl_key_password']
    for jks_type in ('server', 'client', 'server.truststore'):
        jks_path = os.path.join(
            KAFKA_APP_DATA,
            "kafka.{}.jks".format(jks_type)
        )
        log('modifying password')
        # import the pkcs12 into the keystore
        check_call([
            'keytool',
            '-v', '-storepasswd',
            '-new', new_password,
            '-storepass', password,
            '-keystore', jks_path
        ])
    path = os.path.join(
        KAFKA_APP_DATA,
        'keystore.secret'
    )
    if os.path.isfile(path):
        os.remove(path)
        with os.fdopen(
                os.open(path, os.O_WRONLY | os.O_CREAT, 0o440),
                'wb') as f:
            if config['ssl_key_password']:
                token = config['ssl_key_password'].encode("utf-8")
                f.write(token)
    import_srv_crt_to_keystore()
    import_ca_crt_to_keystore()
    remove_state('config.changed.ssl_key_password')
    remove_state('kafka.started')


@when(
    'apt.installed.kafka',
    'zookeeper.ready',
    'kafka.ca.keystore.saved',
    'kafka.server.keystore.saved'
)
@when_not('kafka.started')
def configure_kafka(zk):
    hookenv.status_set('maintenance', 'setting up kafka')
    if hookenv.config()['log_dir']:
       log_dir = hookenv.config()['log_dir']
    else:
       log_dir = unitdata.kv().get('kafka.storage.log_dir')
    kafka = Kafka()
    zks = zk.zookeepers()
    data_changed('kafka.storage.log_dir', log_dir)
    data_changed('zookeepers', zks),
    if log_dir:
        kafka.install(zk_units=zks, log_dir=log_dir)
    else:
        hookenv.status_set(
            'blocked',
            'unable to get storage dir')
    charms.coordinator.acquire('restart')


@when('coordinator.granted.restart')
def restart():
    hookenv.status_set('maintenance', 'Rolling restart')
    kafka = Kafka()
    kafka.daemon_reload()
    if not kafka.is_running():
        kafka.start()
    else:
        kafka.restart()
    hookenv.open_port(hookenv.config()['port'])
    # set app version string for juju status output
    kafka_version = kafka.version()
    hookenv.application_version_set(kafka_version)
    hookenv.status_set('active', 'ready')
    set_state('kafka.started')


@when('config.changed', 'kafka.started', 'zookeeper.ready')
def config_changed(zk):
    for k, v in hookenv.config().items():
        if k.startswith('nagios') and data_changed('kafka.config.{}'.format(k),
                                                    v):
            # Trigger a reconfig of nagios if relation established
            remove_state('kafka.nrpe_helper.registered')
    # Something must have changed if this hook fired, trigger reconfig
    remove_state('config.changed')
    remove_state('kafka.started')


@when(
    'apt.installed.kafka',
    'zookeeper.ready',
    'kafka.ca.keystore.saved',
    'kafka.server.keystore.saved',
    'kafka.started')
def configure_kafka_zookeepers(zk):
    """Configure ready zookeepers and restart kafka if needed.
    As zks come and go, server.properties will be updated. When that file
    changes, restart Kafka and set appropriate status messages.
    """
    zks = zk.zookeepers()
    if hookenv.config()['log_dir']:
       log_dir = hookenv.config()['log_dir']
    else:
       log_dir = unitdata.kv().get('kafka.storage.log_dir')
    if not(any((
            data_changed('zookeepers', zks),
            data_changed('kafka.storage.log_dir', log_dir)))):
        return

    hookenv.log('Checking Zookeeper configuration')
    hookenv.status_set('maintenance', 'updating zookeeper instances')
    kafka = Kafka()
    kafka.install(zk_units=zks, log_dir=log_dir)
    charms.coordinator.acquire('restart')


@when('kafka.started')
@when_not('zookeeper.ready')
def stop_kafka_waiting_for_zookeeper_ready():
    hookenv.status_set('maintenance', 'zookeeper not ready, stopping kafka')
    kafka = Kafka()
    hookenv.close_port(hookenv.config()['port'])
    kafka.stop()
    remove_state('kafka.started')
    hookenv.status_set('waiting', 'waiting for zookeeper to become ready')


@when('client.joined', 'zookeeper.ready')
def serve_client(client, zookeeper):
    if is_state('leadership.is_leader'):
        client.send_port(hookenv.config()['port'],
            hookenv.unit_public_ip())
    else:
        client.send_port(hookenv.config()['port'])

    client.send_zookeepers(zookeeper.zookeepers())
    hookenv.log('Sent Kafka configuration to client')


@when('kafka.started',
      'endpoint.grafana.joined')
def register_grafana_dashboards():
    grafana = endpoint_from_flag('endpoint.grafana.joined')

    # load automatic dashboards
    dash_dir = Path('templates/grafana/autoload')
    for dash_file in dash_dir.glob('kafka.json'):
        dashboard = dash_file.read_text()
        grafana.register_dashboard(dash_file.stem, json.loads(dashboard))
