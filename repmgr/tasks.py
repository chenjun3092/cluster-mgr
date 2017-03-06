import ldap
import redis
import json
import time

from .application import celery, db
from .models import LDAPServer


def log_error_to_redis(r, tid, step, e):
    key = 'task:{0}:{1}'.format(tid, step)
    r.set(key, 'failed')
    if type(e.message) == dict and 'desc' in e.message:
        r.set(key+':error', e.message['desc'])
    else:
        r.set(key+':error', "%s" % e)


@celery.task(bind=True)
def initialize_provider(self, server_id):
    initialized = False
    server = LDAPServer.query.get(server_id)
    ldap.set_option(ldap.OPT_X_TLS_REQUIRE_CERT, ldap.OPT_X_TLS_NEVER)
    r = redis.Redis(host='localhost', port=6379, db=0)
    dn = r'cn=replicator,o=gluu'
    replication_user = [
            ('objectclass', [r'person']),
            ('cn', [r'replicator']),
            ('sn', [r'gluu']),
            ('userpassword', [str(server.replication_pw)])
            ]

    # Step 1: Connection
    try:
        con = ldap.initialize('ldap://{}:{}'.format(
            server.hostname, server.port))
        if server.starttls:
            con.start_tls_s()
        con.bind_s('cn=directory manager,o=gluu', server.admin_pw)
        r.set('task:{}:conn'.format(self.request.id), 'success')
    except ldap.LDAPError as e:
        log_error_to_redis(r, self.request.id, 'conn', e)

    # Step 2: Add replication user
    try:
        con.add_s(dn, replication_user)
        r.set('task:{}:add'.format(self.request.id), 'success')
    except ldap.LDAPError as e:
        log_error_to_redis(r, self.request.id, 'add', e)
    finally:
        con.unbind()

    # Step 3: Reconnect as replication user
    try:
        con = ldap.initialize('ldap://{}:{}'.format(
            server.hostname, server.port))
        if server.starttls:
            con.start_tls_s()
        con.bind_s('cn=replicator,o=gluu', server.replication_pw)
        r.set('task:{}:recon'.format(self.request.id), 'success')
        initialized = True
    except ldap.LDAPError as e:
        log_error_to_redis(r, self.request.id, 'recon', e)
    finally:
        con.unbind()

    if initialized:
        server.initialized = True
        db.session.add(server)
        db.session.commit()


def log_rep_message(r, key, action, status=None, message=None):
    if not status:
        status = 'SUCCESS'
    if not message:
        message = 'Success'
    msg = {'action': action, 'status': status, 'message': message}
    r.rpush(key, json.dumps(msg))


@celery.task(bind=True)
def replicate(self):
    ldap.set_option(ldap.OPT_X_TLS_REQUIRE_CERT, ldap.OPT_X_TLS_NEVER)
    r = redis.Redis(host='localhost', port=6379, db=0)
    key = 'test:{}'.format(self.request.id)
    dn = 'cn=testentry,o=gluu'
    replication_user = [
            ('objectclass', ['person']),
            ('cn', ['testentry']),
            ('sn', ['gluu']),
            ]

    log_rep_message(r, key, 'Listing all providers', 'NOSTATUS')
    providers = LDAPServer.query.filter_by(role="provider").all()

    for provider in providers:
        # connect to the server
        procon = ldap.initialize('ldap://{}:{}'.format(
            provider.hostname, provider.port))
        try:
            if provider.starttls:
                procon.start_tls_s()
            procon.bind_s('cn=directory manager,o=gluu', provider.admin_pw)
            log_rep_message(r, key, 'Connecting to the provider: {}'.format(
                provider.hostname))
            # add a entry to the server
            procon.add_s(dn, replication_user)
            log_rep_message(
                r, key, 'Adding the test entry {} to the provider'.format(dn))
        except ldap.LDAPError as e:
            log_rep_message(
                r, key, 'Adding test data to the provider: {}'.format(
                    provider.hostname), 'FAILED', "{}".format(e))
            continue

        consumers = provider.consumers
        log_rep_message(
            r, key, 'Listing consumers linked to the provider {}: {}'.format(
                provider.hostname, len(consumers)), 'NOSTATUS')
        # get list of all the consumers
        for consumer in consumers:
            log_rep_message(
                r, key, 'Verifying data in consumers: {} of {}'.format(
                    consumers.index(consumer)+1, len(consumers)))
            con = ldap.initialize('ldap://{}:{}'.format(consumer.hostname,
                                                        consumer.port))
            try:
                if consumer.starttls:
                    con.start_tls_s()
                con.bind_s('cn=directory manager,o=gluu', consumer.admin_pw)
                log_rep_message(r, key,
                                'Connecting to the consumer: {}'.format(
                                    consumer.hostname))
            except ldap.LDAPError as e:
                log_rep_message(r, key,
                                'Connecting to the consumer: {}'.format(
                                    consumer.hostname), 'FAILED',
                                "{}".format(e))
                continue

            log_rep_message(r, key, 'Searching for the test data', 'NOSTATUS')
            # fetch the data from each consumer and verify the new entry exists
            for i in range(5):
                if con.compare_s(dn, 'sn', 'gluu'):
                    log_rep_message(
                        r, key,
                        'Test data is replicated and available in consumer.')
                    break
                else:
                    log_rep_message(
                        r, key,
                        'Test data not found. Retrying in 3 secs.', 'NOSTATUS')
                    time.sleep(3)
            con.unbind()

        # delete the entry from the provider
        persists = False
        try:
            procon.delete_s(dn)
            persists = procon.compare_s(dn, 'sn', 'gluu')
            if persists:
                log_rep_message(r, key, 'Deleting test entry from provider',
                                'FAILED', 'Entry still persists.')
        except ldap.NO_SUCH_OBJECT:
            log_rep_message(r, key, 'Deleting test entry from the provider')
        except ldap.LDAPError as e:
            log_rep_message(r, key, 'Deleting test entry from provider',
                            'FAILED', "{}".format(e))
        finally:
            procon.unbind()

        # verify the data is removed from the consumers
        for consumer in consumers:
            log_rep_message(
                r, key,
                "Verifying data is removed from consumers: {} of {}".format(
                    consumers.index(consumer)+1, len(consumers)))
            con = ldap.initialize('ldap://{}:{}'.format(consumer.hostname,
                                                        consumer.port))
            persists = False
            try:
                if consumer.starttls:
                    con.start_tls_s()
                persists = con.compare_s(dn, 'sn', 'gluu')
                if persists:
                    log_rep_message(r, key, 'Deleting test entry from provider',
                                    'FAILED', 'Entry still persists.')
            except ldap.NO_SUCH_OBJECT:
                log_rep_message(r, key, 'Test data removed from the consumer {}'.format(consumer.hostname))
            except ldap.LDAPError as e:
                log_rep_message(r, key, 'Test data removed from the consumer {}'.format(consumer.hostname),
                                'FAILED', "{}".format(e))
            finally:
                con.unbind()

    log_rep_message(r, key, 'Test Complete.')
