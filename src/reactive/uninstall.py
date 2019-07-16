from charmhelpers.core import hookenv

from charms.reactive import hook, set_flag

from charms import apt


@hook('stop')
def uninstall():
    try:
        apt.remove('kafka')
    except Exception as e:
        # log errors but do not fail stop hook
        hookenv.log('failed to remove kafka: {}'.format(e), hookenv.ERROR)
    finally:
        set_flag('kafka.departed')
