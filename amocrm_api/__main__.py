from requests_client.__main__ import main
from sys import argv


if __name__ == '__main__':
    main(['amocrm_api.AmocrmClient'] + argv[1:])
