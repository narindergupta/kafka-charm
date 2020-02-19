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
from charms.layer.kafka import Kafka
from charms.layer.kafka import keystore_password, KAFKA_APP_DATA
from charms.layer.kafka import ca_crt_path
from charms.layer.kafka import server_crt_path
from charms.layer.kafka import server_key_path
from charms.layer.kafka import client_crt_path
from charms.layer.kafka import client_key_path
from charms.layer import tls_client
from charmhelpers.core import hookenv, unitdata
from charms.reactive import (when, when_not, hook, when_file_changed,
                             remove_state, set_state, endpoint_from_flag,
                             set_flag)
from charms.reactive.helpers import data_changed
from charmhelpers.core.hookenv import log


@when('apt.installed.kafka')
@when_not('zookeeper.joined')
def waiting_for_zookeeper():
    kafka = Kafka()
    kafka.stop()
    kafka.install()
    hookenv.status_set('blocked', 'waiting for relation to zookeeper')


@when('apt.installed.kafka', 'zookeeper.joined')
@when_not('kafka.started', 'zookeeper.ready')
def waiting_for_zookeeper_ready(zk):
    kafka = Kafka()
    kafka.stop()
    kafka.install()
    hookenv.status_set('waiting', 'waiting for zookeeper to become ready')


@hook('upgrade-charm')
def upgrade_charm():
    update_certificates()
    remove_state('kafka.nrpe_helper.installed')
    remove_state('kafka.started')


@when_not('kafka.ca.keystore.saved', 'kafka.server.keystore.saved')
@when('apt.installed.kafka')
def waiting_for_certificates():
    kafka = Kafka()
    kafka.stop()
    kafka.install()
    if config['ssl_cert']:
        set_state('certificates.available')
    else:
        hookenv.status_set('waiting', 'Waiting relation to certificate authority.')


@when('certificates.available', 'apt.installed.kafka')
def send_data():
    '''Send the data that is required to create a server certificate for
    this server.'''
    config = hookenv.config()
    if config['ssl_cert']:
        with open(server_crt_path, "wb") as fs:
            os.chmod(server_crt_path, stat.S_IRUSR |
                         stat.S_IWUSR |
                         stat.S_IRGRP |
                         stat.S_IROTH)
            fs.write(base64.b64decode(config['ssl_cert']))
        with open(client_crt_path, "wb") as fc:
            os.chmod(client_crt_path, stat.S_IRUSR |
                         stat.S_IWUSR |
                         stat.S_IRGRP |
                         stat.S_IROTH)
            fc.write(base64.b64decode(config['ssl_cert']))
        if config['ssl_key']:
            with open(server_key_path, "wb") as fks:
                os.chmod(server_key_path, stat.S_IWUSR |
                              stat.S_IWUSR )
                fks.write(base64.b64decode(config['ssl_key']))
            with open(client_key_path, "wb") as fkc:
                os.chmod(client_key_path, stat.S_IWUSR |
                              stat.S_IWUSR )
                fkc.write(base64.b64decode(config['ssl_key']))
        if config['ssl_ca']:
            with open(ca_crt_path, "wb") as fca:
                os.chmod(ca_crt_path, stat.S_IRUSR |
                         stat.S_IWUSR |
                         stat.S_IRGRP |
                         stat.S_IROTH)
                fca.write(base64.b64decode(config['ssl_ca']))
        import_srv_crt_to_keystore()
        import_ca_crt_to_keystore()
    else:
        common_name = hookenv.unit_private_ip()
        common_public_name = hookenv.unit_public_ip()
        sans = [
            common_name,
            common_public_name,
            hookenv.unit_public_ip(),
            socket.gethostname(),
            socket.getfqdn(),
        ]

        # maybe they have extra names they want as SANs
        extra_sans = hookenv.config('subject_alt_names')
        if extra_sans and not extra_sans == "":
            sans.extend(extra_sans.split())

        # Request a server cert with this information.
        tls_client.request_server_cert(common_name, sans,
                                   crt_path=server_crt_path,
                                   key_path=server_key_path)

        # Request a client cert with this information.
        tls_client.request_client_cert(common_name, sans,
                                   crt_path=client_crt_path,
                                   key_path=client_key_path)


@when('tls_client.certs.changed')
def import_srv_crt_to_keystore():
    for cert_type in ('server', 'client'):
        password = keystore_password()
        crt_path = os.path.join(
            KAFKA_APP_DATA,
            "{}.crt".format(cert_type)
        )
        key_path = os.path.join(
            KAFKA_APP_DATA,
            "{}.key".format(cert_type)
        )

        if os.path.isfile(crt_path) and os.path.isfile(key_path):
            with open(crt_path, 'rt') as f:
                cert = f.read()
                loaded_cert = crypto.load_certificate(
                    crypto.FILETYPE_PEM,
                    cert
                )
                if not data_changed(
                    'kafka_{}_certificate'.format(cert_type),
                    cert
                ):
                    log('server certificate of key file missing')
                    return

            with open(key_path, 'rt') as f:
                loaded_key = crypto.load_privatekey(
                    crypto.FILETYPE_PEM,
                    f.read()
                )

            with tempfile.NamedTemporaryFile() as tmp:
                log('server certificate changed')

                keystore_path = os.path.join(
                    KAFKA_APP_DATA,
                    "kafka.{}.jks".format(cert_type)
                )

                pkcs12 = crypto.PKCS12Type()
                pkcs12.set_certificate(loaded_cert)
                pkcs12.set_privatekey(loaded_key)
                pkcs12_data = pkcs12.export(password)
                log('opening tmp file {}'.format(tmp.name))

                # write cert and private key to the pkcs12 file
                tmp.write(pkcs12_data)
                tmp.flush()

                log('importing pkcs12')
                # import the pkcs12 into the keystore
                check_call([
                    'keytool',
                    '-v', '-importkeystore',
                    '-srckeystore', str(tmp.name),
                    '-srcstorepass', password,
                    '-srcstoretype', 'PKCS12',
                    '-destkeystore', keystore_path,
                    '-deststoretype', 'JKS',
                    '-deststorepass', password,
                    '--noprompt'
                ])

                remove_state('kafka.started')
                remove_state('tls_client.certs.changed')
                set_state('kafka.{}.keystore.saved'.format(cert_type))


@when('tls_client.ca_installed')
@when_not('kafka.ca.keystore.saved')
def import_ca_crt_to_keystore():
    if os.path.isfile(ca_path):
        with open(ca_crt_path, 'rt') as f:
            changed = data_changed('ca_certificate', f.read())

        if changed:
            ca_keystore = os.path.join(
                KAFKA_APP_DATA,
                "kafka.server.truststore.jks"
            )
            check_call([
                'keytool',
                '-import', '-trustcacerts', '-noprompt',
                '-keystore', ca_keystore,
                '-storepass', keystore_password(),
                '-file', ca_crt_path
            ])

            remove_state('tls_client.ca_installed')
            set_state('kafka.ca.keystore.saved')


@when('config.changed.subject_alt_names', 'certificates.available',
      'kafka.started')
def update_certificates():
    # Using the config.changed.extra_sans flag to catch changes.
    # IP changes will take ~5 minutes or so to propagate, but
    # it will update.
    send_data()
    remove_state('config.changed.subject_alt_names')


@when('tls_client.ca.written')
def ca_written():
    remove_state('kafka.started')
    remove_state('tls_client.ca.written')


@when(
    'apt.installed.kafka',
    'zookeeper.ready',
    'kafka.ca.keystore.saved',
    'kafka.server.keystore.saved'
)
@when_not('kafka.started')
def configure_kafka(zk):
    hookenv.status_set('maintenance', 'setting up kafka')
    log_dir = hookenv.config()['log_dir']
    kafka = Kafka()
    zks = zk.zookeepers()
    kafka.install(zk_units=zks, log_dir=log_dir)
    hookenv.open_port(hookenv.config()['port'])
    # set app version string for juju status output
    kafka_version = kafka.version()
    hookenv.application_version_set(kafka_version)
    hookenv.status_set('active', 'ready')
    kafka.restart()
    set_state('kafka.started')


@when('config.changed', 'kafka.started', 'zookeeper.ready')
def config_changed(zk):
    for k, v in hookenv.config().items():
        if k.startswith('nagios') and data_changed('kafka.config.{}'.format(k),
                                                   v):
            # Trigger a reconfig of nagios if relation established
            remove_state('kafka.nrpe_helper.registered')
    # Something must have changed if this hook fired, trigger reconfig
    remove_state('kafka.started')


@when('kafka.started', 'zookeeper.ready')
def configure_kafka_zookeepers(zk):
    """Configure ready zookeepers and restart kafka if needed.
    As zks come and go, server.properties will be updated. When that file
    changes, restart Kafka and set appropriate status messages.
    """
    zks = zk.zookeepers()
    log_dir = hookenv.config()['log_dir']
    if not((
            data_changed('zookeepers', zks))):
        return

    hookenv.log('Checking Zookeeper configuration')
    hookenv.status_set('maintenance', 'updating zookeeper instances')
    kafka = Kafka()
    kafka.install(zk_units=zks, log_dir=log_dir)
    kafka.restart()
    hookenv.status_set('active', 'ready')


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
