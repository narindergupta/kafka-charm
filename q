[1mdiff --git a/src/lib/charms/layer/kafka.py b/src/lib/charms/layer/kafka.py[m
[1mindex 2e66b04..0f9da9c 100755[m
[1m--- a/src/lib/charms/layer/kafka.py[m
[1m+++ b/src/lib/charms/layer/kafka.py[m
[36m@@ -22,7 +22,7 @@[m [mimport time[m
 from pathlib import Path[m
 from base64 import b64encode, b64decode[m
 [m
[31m-from charmhelpers.core import hookenv, host[m
[32m+[m[32mfrom charmhelpers.core import host, hookenv, unitdata[m
 from charmhelpers.core.templating import render[m
 [m
 from charms.reactive.relations import RelationBase[m
[36m@@ -56,10 +56,29 @@[m [mclass Kafka(object):[m
         zk_connect = ','.join(zks)[m
 [m
         config = hookenv.config()[m
[31m-        log_dir = config['log_dir'][m
[31m-[m
[32m+[m[32m        broker_id = None[m
[32m+[m[32m        storageids = hookenv.storage_list('logs')[m
[32m+[m[32m        if storageids:[m
[32m+[m[32m            mount = hookenv.storage_get('location', storageids[0])[m
[32m+[m
[32m+[m[32m            if mount:[m
[32m+[m[32m                broker_path = os.path.join(log_dir, '.broker_id')[m
[32m+[m
[32m+[m[32m                if os.path.isfile(broker_path):[m
[32m+[m[32m                    with open(broker_path, 'r') as f:[m
[32m+[m[32m                        try:[m
[32m+[m[32m                            broker_id = int(f.read().strip())[m
[32m+[m[32m                        except ValueError:[m
[32m+[m[32m                            hookenv.log('{}'.format([m
[32m+[m[32m                                'invalid broker id format'))[m
[32m+[m[32m                            hookenv.status_set([m
[32m+[m[32m                                'blocked',[m
[32m+[m[32m                                'unable to validate broker id format')[m
[32m+[m[32m                            raise[m
[32m+[m
[32m+[m[32m            #'broker_id': os.environ['JUJU_UNIT_NAME'].split('/', 1)[1],[m
         context = {[m
[31m-            'broker_id': os.environ['JUJU_UNIT_NAME'].split('/', 1)[1],[m
[32m+[m[32m            'broker_id': broker_id,[m
             'port': config['port'],[m
             'zookeeper_connection_string': zk_connect,[m
             'log_dirs': log_dir,[m
[1mdiff --git a/src/metadata.yaml b/src/metadata.yaml[m
[1mindex 82db2fe..a65f6b0 100644[m
[1m--- a/src/metadata.yaml[m
[1m+++ b/src/metadata.yaml[m
[36m@@ -31,6 +31,14 @@[m [mrequires:[m
     interface: tls-certificates[m
   zookeeper:[m
     interface: zookeeper[m
[32m+[m[32mstorage:[m
[32m+[m[32m  logs:[m
[32m+[m[32m    type: filesystem[m
[32m+[m[32m    description: Directory where log files will be stored[m
[32m+[m[32m    minimum-size: 20M[m
[32m+[m[32m    location: /media/kafka[m
[32m+[m[32m    multiple:[m
[32m+[m[32m      range: "0-1"[m
 min-juju-version: "2.6.0"[m
 series:[m
 - bionic[m
[1mdiff --git a/src/reactive/kafka.py b/src/reactive/kafka.py[m
[1mindex ec9bbdf..8ee2128 100644[m
[1m--- a/src/reactive/kafka.py[m
[1m+++ b/src/reactive/kafka.py[m
[36m@@ -52,11 +52,12 @@[m [mdef waiting_for_zookeeper_ready(zk):[m
     hookenv.status_set('waiting', 'waiting for zookeeper to become ready')[m
 [m
 [m
[31m-@hook('upgrade-charm')[m
[31m-def upgrade_charm():[m
[31m-    update_certificates()[m
[31m-    remove_state('kafka.nrpe_helper.installed')[m
[31m-    remove_state('kafka.started')[m
[32m+[m[32m@when_not([m
[32m+[m[32m    'kafka.storage.logs.attached'[m
[32m+[m[32m)[m
[32m+[m[32m@when('apt.installed.kafka')[m
[32m+[m[32mdef waiting_for_storage_attach():[m
[32m+[m[32m    hookenv.status_set('waiting', 'waiting for storage attachment')[m
 [m
 [m
 @when_not('kafka.ca.keystore.saved',[m
[36m@@ -297,12 +298,20 @@[m [mdef ca_written():[m
 @when_not('kafka.started')[m
 def configure_kafka(zk):[m
     hookenv.status_set('maintenance', 'setting up kafka')[m
[31m-    log_dir = hookenv.config()['log_dir'][m
[32m+[m[32m    log_dir = unitdata.kv().get('kafka.storage.log_dir')[m
[32m+[m[32m    data_changed('kafka.storage.log_dir', log_dir)[m
[32m+[m
     kafka = Kafka()[m
     if kafka.is_running():[m
         kafka.stop()[m
     zks = zk.zookeepers()[m
[31m-    kafka.install(zk_units=zks, log_dir=log_dir)[m
[32m+[m[32m    if log_dir:[m
[32m+[m[32m        kafka.install(zk_units=zks, log_dir=log_dir)[m
[32m+[m[32m    else:[m
[32m+[m[32m        hookenv.status_set([m
[32m+[m[32m            'blocked',[m
[32m+[m[32m            'unable to get storage dir')[m
[32m+[m
     if not kafka.is_running():[m
         kafka.start()[m
     hookenv.open_port(hookenv.config()['port'])[m
[36m@@ -337,9 +346,10 @@[m [mdef configure_kafka_zookeepers(zk):[m
     changes, restart Kafka and set appropriate status messages.[m
     """[m
     zks = zk.zookeepers()[m
[31m-    log_dir = hookenv.config()['log_dir'][m
[31m-    if not(([m
[31m-            data_changed('zookeepers', zks))):[m
[32m+[m[32m    log_dir = unitdata.kv().get('kafka.storage.log_dir')[m
[32m+[m[32m    if not(any(([m
[32m+[m[32m            data_changed('zookeepers', zks),[m
[32m+[m[32m            data_changed('kafka.storage.log_dir', log_dir)))):[m
         return[m
 [m
     hookenv.log('Checking Zookeeper configuration')[m
