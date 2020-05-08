import os
import socket
import tempfile

from OpenSSL import crypto
from subprocess import check_call

from charms.layer import tls_client
from charms.layer.kafka import (keystore_password, caKeystore,
                                caPath, crtPath, keyPath,
                                keystore, keystoreSecret)

from charmhelpers.core import hookenv, unitdata

from charms.reactive import (when, when_file_changed, remove_state,
                             when_not, set_state)
from charms.reactive.helpers import data_changed

from charmhelpers.core.hookenv import log


@when('certificates.available')
def send_data():
    # Send the data that is required to create a server certificate for
    # this server.
    config = hookenv.config()
    server_crt_path = crtPath('server')
    client_crt_path = crtPath('client')
    server_key_path = keyPath('server')
    client_key_path = keyPath('client')
    ca_crt_path = caPath()
    # Use the private ip of this unit as the Common Name for the certificate.
    if config['ssl_cert']:
        for certs_path in ('server_crt_path', 'client_crt_path'):
            with open(certs_path, "wb") as fs:
                os.chmod(certs_path, stat.S_IRUSR |
                         stat.S_IWUSR |
                         stat.S_IRGRP |
                         stat.S_IROTH)
                fs.write(base64.b64decode(config['ssl_cert']))
            if config['ssl_key']:
                with open(certs_path, "wb") as fks:
                    os.chmod(certs_path, stat.S_IWUSR |
                              stat.S_IWUSR )
                    fks.write(base64.b64decode(config['ssl_key']))
        import_srv_crt_to_keystore()
        if config['ssl_ca']:
            with open(ca_crt_path, "wb") as fca:
                os.chmod(ca_crt_path, stat.S_IRUSR |
                         stat.S_IWUSR |
                         stat.S_IRGRP |
                         stat.S_IROTH)
                fca.write(base64.b64decode(config['ssl_ca']))
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


@when_file_changed(keystore('server'))
@when_file_changed(keystore('client'))
@when('kafka.started')
def restart_when_keystore_changed():
    remove_state('kafka.started')


@when('tls_client.certs.changed')
def import_srv_crt_to_keystore():
    for cert_type in ('server', 'client'):
        password = keystore_password()
        crt_path = crtPath(cert_type)
        key_path = keyPath(cert_type)

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

                keystore_path = keystore(cert_type)

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
                os.chmod(keystore_path, 0o444)

                remove_state('tls_client.certs.changed')
                set_state('kafka.{}.keystore.saved'.format(cert_type))


@when('tls_client.ca_installed')
@when_not('kafka.ca.keystore.saved')
def import_ca_crt_to_keystore():
    ca_path = caPath()

    if os.path.isfile(ca_path):
        with open(ca_path, 'rt') as f:
            changed = data_changed('ca_certificate', f.read())

        if changed:
            ca_keystore = caKeystore()
            check_call([
                'keytool',
                '-import', '-trustcacerts', '-noprompt',
                '-keystore', ca_keystore,
                '-storepass', keystore_password(),
                '-file', ca_path
            ])
            os.chmod(ca_keystore, 0o444)

            remove_state('tls_client.ca_installed')
            set_state('kafka.ca.keystore.saved')


@when('endpoint.certificates.departed')
def clear_certificates():
    ca_path = caPath()
    ca_keystore = caKeystore()
    ca_keystore_secret = keystoreSecret()
    if os.path.exists(ca_path):
        os.remove(ca_path)
    if os.path.exists(ca_keystore):
        os.remove(ca_keystore)
    if os.path.exists(ca_keystore_secret):
        os.remove(ca_keystore_secret)

    certs_paths = unitdata.kv().get('layer.tls-client.cert-paths', {})
    for cert_type in ('server', 'client'):
        crt_path = crtPath(cert_type)
        key_path = keyPath(cert_type)
        keystore_path = keystore(cert_type)
        if os.path.exists(crt_path):
            os.remove(crt_path)
        if os.path.exists(key_path):
            os.remove(key_path)
        if os.path.exists(keystore_path):
            os.remove(keystore_path)
        remove_state('kafka.{}.keystore.saved'.format(cert_type))
        data_changed('kafka_{}_certificate'.format(cert_type), {})

        for common_name, paths in certs_paths.get(cert_type, {}).items():
            data_changed('layer.tls-client.'
                         '{}.{}'.format(cert_type, common_name), {})

    # We need to clean up data because the underlying layer
    # failes to clear flags and data_changed states when
    # we remove {charm}-easyrsa relation.
    unitdata_keys = (
        'reactive.tls_client',
        'reactive.data_changed.endpoint.certificates',
        'reactive.data_changed.ca_certificate',
        'reactive.data_changed.certificate',
        'reactive.data_changed.client',
        'reactive.data_changed.server',
        'reactive.data_changed.kafka_client_certificate',
        'reactive.data_changed.kafka_server_certificate',
        'reactive.states.endpoint.certificates',
        'reactive.states.tls_client'
    )

    for k in unitdata_keys:
        unitdata.kv().unsetrange(None, k)

    cleanup_states = (
        'kafka.ca.keystore.saved',
        'tls_client.ca.saved',
        'tls_client.server.certificate.saved',
        'tls_client.server.key.saved',
        'tls_client.client.certificate.saved',
        'tls_client.client.key.saved',
        'kafka.started'
    )
    for s in cleanup_states:
        remove_state(s)
