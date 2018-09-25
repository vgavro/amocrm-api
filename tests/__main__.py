# Startup file for IPython
# To use start ipython: `./env/bin/ipython -i tests`

import os.path
import logging
import sys  # noqa

from IPython import get_ipython
import yaml
import coloredlogs
from requests_client.utils import maybe_attr_dict, pprint  # noqa

from amocrm_api import client as client_
from amocrm_api.constants import *  # noqa

try:
    from importlib import reload
except ImportError:
    pass  # already in builtins for Python < 3.4


coloredlogs.DEFAULT_FIELD_STYLES['asctime'] = {'color': 'magenta'}
coloredlogs.install(level=1, datefmt='%H:%M:%S',
                    fmt='%(asctime)s.%(msecs)03d %(levelname)s %(name)s %(message)s')

# Turn off verbose debugs on ipython autocomplete
logging.getLogger('parso').propagate = False

ip = get_ipython()
ip.run_line_magic('load_ext', 'autoreload')
ip.run_line_magic('autoreload', '2')  # smart autoreload modules on changes

variables = maybe_attr_dict(yaml.load(open(os.path.join(os.path.dirname(__file__),
                                           'variables.yaml'), 'rb').read()))
vars = variables

for arg in sys.argv[1:]:
    if arg.startswith('--variables='):
        variables.update(maybe_attr_dict(yaml.load(open(arg[12:], 'rb').read())))
    else:
        print('Unknown argument: {}'.format(arg))


def create_client(**kwargs):
    reload(client_)
    return client_.AmocrmClient(
        login=vars.account.login, hash=vars.account.hash,
        domain=vars.account.domain, **kwargs
    )


client = create_client()
