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

import os
import shutil
import re
import socket

from pathlib import Path
from base64 import b64encode, b64decode

from charmhelpers.core import hookenv, host
from charmhelpers.core.templating import render

from charms.reactive.relations import RelationBase

from charms import apt

KAFKA_APP = 'kafka'
KAFKA_SERVICE = '{}.service'.format(KAFKA_APP)
KAFKA_APP_DATA = '/etc/{}'.format(KAFKA_APP)
KAFKA_SERVICE_CONF = '/lib/systemd/system/'
KAFKA_BIN = '/usr/lib/kafka/bin/'
certs_dir = Path('/etc/kafka')
ca_crt_path = '/usr/local/share/ca-certificates/kafka.crt'
server_crt_path = certs_dir / 'server.crt'
server_key_path = certs_dir / 'server.key'
client_crt_path = certs_dir / 'client.crt'
client_key_path = certs_dir / 'client.key'


class Kafka(object):
    def install(self, zk_units=[], log_dir='logs'):
        '''
        Generates client-ssl.properties and server.properties with the current
        system state.
        '''
        zks = []
        for unit in zk_units or self.get_zks():
            ip = resolve_private_address(unit['host'])
            zks.append('%s:%s' % (ip, unit['port']))
        zks.sort()
        zk_connect = ','.join(zks)

        config = hookenv.config()
        log_dir = config['log_dir']

        context = {
            'broker_id': os.environ['JUJU_UNIT_NAME'].split('/', 1)[1],
            'port': config['port'],
            'zookeeper_connection_string': zk_connect,
            'log_dirs': log_dir,
            'keystore_password': keystore_password(),
            'ca_keystore': os.path.join(
                KAFKA_APP_DATA,
                'kafka.server.truststore.jks'
            ),
            'server_keystore': os.path.join(
                KAFKA_APP_DATA,
                'kafka.server.jks'
            ),
            'client_keystore': os.path.join(
                KAFKA_APP_DATA,
                'kafka.client.jks'
            ),
            'bind_addr': hookenv.unit_private_ip(),
            'adv_bind_addr': hookenv.unit_public_ip(),
            'auto_create_topics': config['auto_create_topics'],
            'default_partitions': config['default_partitions'],
            'default_replication_factor': config['default_replication_factor'],
            'service_environment': config['service_environment'],
            'service_parameter': config['service_parameter'],
            'kafka_jmx_port': config['kafka_jmx_port'],
            'kafka_jmx_opts': config['kafka_jmx_opts'],
            'inter_broker_protocol_version':
                config.get('inter_broker_protocol_version'),
            'log_message_format_version':
                config.get('log_message_format_version'),
        }

        if log_dir:
            os.makedirs(log_dir, mode=0o755, exist_ok=True)
            shutil.chown(log_dir, user='kafka')

        render(
            source='consumer.properties',
            target=os.path.join(KAFKA_APP_DATA, 'consumer.properties'),
            owner='root',
            perms=0o400,
            context=context
        )

        render(
            source='producer.properties',
            target=os.path.join(KAFKA_APP_DATA, 'producer.properties'),
            owner='root',
            perms=0o400,
            context=context
        )

        render(
            source='connect-standalone.properties',
            target=os.path.join(KAFKA_APP_DATA, 'connect-standalone.properties'),
            owner='root',
            perms=0o400,
            context=context
        )

        render(
            source='connect-distributed.properties',
            target=os.path.join(KAFKA_APP_DATA, 'connect-distributed.properties'),
            owner='root',
            perms=0o400,
            context=context
        )

        render(
            source='client-ssl.properties',
            target=os.path.join(KAFKA_APP_DATA, 'client-ssl.properties'),
            owner='root',
            perms=0o400,
            context=context
        )

        render(
            source='server.properties',
            target=os.path.join(KAFKA_APP_DATA, 'server.properties'),
            owner='root',
            perms=0o644,
            context=context
        )

        render(
            source='kafka.service',
            target=os.path.join(KAFKA_SERVICE_CONF, 'kafka.service'),
            owner='root',
            perms=0o644,
            context=context
        )

        render(
            source='broker.env',
            target=os.path.join(KAFKA_APP_DATA, 'broker.env'),
            owner='root',
            perms=0o644,
            context=context
        )

        render(
            source='kafka-server-wrapper.sh',
            target=os.path.join(KAFKA_BIN, 'kafka-server-wrapper.sh'),
            owner='root',
            perms=0o755,
            context=context
        )

        extraconfig = b64decode(config['extra_config']).decode("utf-8")
        with open(os.path.join(KAFKA_APP_DATA, 'server.properties'), "a") as outfile:
            outfile.write(extraconfig)
            outfile.close()

    def restart(self):
        '''
        Restarts the Kafka service.
        '''
        host.service_restart(KAFKA_SERVICE)

    def start(self):
        '''
        Starts the Kafka service.
        '''
        host.service_reload(KAFKA_SERVICE)

    def stop(self):
        '''
        Stops the Kafka service.

        '''
        host.service_stop(KAFKA_SERVICE)

    def is_running(self):
        '''
        Restarts the Kafka service.
        '''
        return host.service_running(KAFKA_SERVICE)

    def get_zks(self):
        '''
        Will attempt to read zookeeper nodes from the zookeeper.joined state.

        If the flag has never been set, an empty list will be returned.
        '''
        zk = RelationBase.from_flag('zookeeper.joined')
        if zk:
            return zk.zookeepers()
        else:
            return []

    def version(self):
        '''
        Will attempt to get the version from the version fieldof the
        Kafka application.

        If there is a reader exception or a parser exception, unknown
        will be returned
        '''
        return apt.get_package_version(KAFKA_APP) or 'unknown'


def keystore_password():
    path = os.path.join(
        KAFKA_APP_DATA,
        'keystore.secret'
    )
    config = hookenv.config()
    if not os.path.isfile(path):
        with os.fdopen(
                os.open(path, os.O_WRONLY | os.O_CREAT, 0o440),
                'wb') as f:
            if config['ssl_key_password']:
                token = config['ssl_key_password'].encode("utf-8")
            else:
                token = b64encode(os.urandom(32))
            token = b64encode(os.urandom(32))
            f.write(token)
            password = token.decode('ascii')
    else:
        password = Path(path).read_text().rstrip()
    return password


def resolve_private_address(addr):
    IP_pat = re.compile(r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}')
    contains_IP_pat = re.compile(r'\d{1,3}[-.]\d{1,3}[-.]\d{1,3}[-.]\d{1,3}')
    if IP_pat.match(addr):
        return addr  # already IP
    try:
        ip = socket.gethostbyname(addr)
        return ip
    except socket.error as e:
        hookenv.log(
            'Unable to resolve private IP: %s (will attempt to guess)' %
            addr,
            hookenv.ERROR
        )
        hookenv.log('%s' % e, hookenv.ERROR)
        contained = contains_IP_pat.search(addr)
        if not contained:
            raise ValueError(
                'Unable to resolve private-address: {}'.format(addr)
            )
        return contained.groups(0).replace('-', '.')
