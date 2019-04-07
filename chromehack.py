import os
import pycookiecheat


if os.path.isfile('chromepassword.txt'):
    with open('chromepassword.txt') as f:
        chrometype, chromepassword = f.read().split()
        get_linux_config = pycookiecheat.pycookiecheat.get_linux_config
        def new_get_linux_config(browser):
            config = get_linux_config(browser)
            config['my_pass'] = chromepassword
            return config
        pycookiecheat.pycookiecheat.get_linux_config = new_get_linux_config
else:
    chromepassword = chrometype = None


def get_session_cookie():
    if chrometype is None:
        return None
    try:
        return pycookiecheat.chrome_cookies('https://worldroulette.ru/', browser=chrometype)['session']
    except Exception:
        return None
