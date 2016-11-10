#!/usr/bin/python3

import requests
import hyper.contrib
import re
import json
import time
import sys
import threading
import queue
ROLL_INTERVAL = 5
USER_AGENT = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/53.0.2763.0 Safari/537.36'


class Bot:
    host = 'https://worldroulette.ru/'

    def __init__(self, login, password, no_proxy=False):
        self.login = login.lower()
        self.password = password
        if no_proxy:
            self.proxy = None
        else:
            self.proxy = proxy[0]
            print('Using proxy', proxy[0], 'for', login)
            proxy.pop(0)
        self.auth()

    def auth(self):
        if self.proxy:
            print('Proxies are not supported yet')
        self.opener = requests.session()
        self.opener.mount(self.host, hyper.contrib.HTTP20Adapter())
        self.opener.cookies['session'] = self.password
        pg = self.open('')
        self.rolls_since_captcha = 50

    def logout(self):
        pg = self.open('')
        opts = {i:j for i,j in re.findall(r'<input type="hidden" name="([^"]+)" value="([^"]+)" />', pg) if '_' not in i}
        opts['Submit'] = 'Выйти'
        self.open('', opts)

    def genCode(self, country):
        a = 'rand' + country + '0'
        b = 0
        for i in a:
            b *= 31
            b += ord(i)
            if b < 0:
                b += 2**32
            b %= 2**32
        return {'a': b, 'b': 0}

    def open(self, uri, params=None):
        headers = {'Connection': None, 'User-agent': USER_AGENT}
        try:
            if params is None:
                resp = self.opener.get(self.host + uri, headers=headers)
            else:
                if isinstance(params, str):
                    headers['Content-type'] = 'application/json'
                resp = self.opener.post(self.host + uri, headers=headers, data=params)
            return resp.text
        except Exception as e:
            self.auth()
            return self.open(uri, params)

    def getMapInfo(self):
        pg = json.loads(self.open('gethint', {}).replace('\n', ' ').strip())
        self.user_to_frac = {}
        self.map = {}
        for i in pg:
            self.user_to_frac[pg[i]['User']] = pg[i]['Faction'] or '<none>'
            self.map[i] = (pg[i]['User'], pg[i]['sp'], pg[i]['Faction'] or '<none>')

    def fight(self, country, last_error=''):
        try:
            d = self.genCode(country)
            d['target'] = country
            d['captcha'] = ''
            res = self.open('roll', json.dumps(d))
            time.sleep(ROLL_INTERVAL)
            if not res:
                return self.fight(country)
            res = json.loads(res)
            if res['result'] == 'success':
                if 'вы успешно захватили' in res['data']:
                    print('Conquered')
                    return True
                else:
                    print('*', end='', flush=True)
                    return False
            elif res['result'] == 'fail':
                print('.', end='', flush=True)
                return False
            elif res['result'] == 'error':
                if res['data'] != last_error and res['data'] != 'Подождите немного!':
                    print('[{}]'.format(res['data']), end='', flush=True)
                return self.fight(country, res['data'])
        except Exception as e:
            print(e)
            time.sleep(1)
            return False

    def conquerCountry(self, country):
        if self.map[country][0].lower() == self.login:
            return
        print('{}: conquering {} ({}), level {}, belongs to {}'.format(self.login, country, countries[country], self.map[country][1], self.map[country][0]))
        while not self.fight(country):
            pass

    def giveAll(self, user):
        if self.login != user:
            self.open('give.php', {'All': 'true', 'auid': user})

class BotManager:
    def __init__(self, lp):
        self.bots = [Bot(l, p, l==lp[0][0]) for l, p in lp]
        self.bots[0].getMapInfo()
        self.logins = [i[0].lower() for i in lp]
        self.queue = queue.Queue(1)

    def sorted_map(self):
        return sorted(self.bots[0].map, key=lambda x:(self.bots[0].map[x][1], x))

    def conquer(self, object_list):
        threads = [threading.Thread(target=lambda i=i:self.work(i, self.bots[0].login)) for i in self.bots]
        for i in threads:
            i.start()
            time.sleep(2)
        self.bots[0].getMapInfo()
        tmap = self.sorted_map()
        for name in tmap:
            if name.lower() in object_list or self.bots[0].map[name][0].lower() in object_list or '*' in object_list:
                if self.bots[0].map[name][0].lower() in self.logins:
                    continue
                self.queue.put(name)
                self.bots[0].getMapInfo()
        for i in self.bots:
            if i.opener is not None:
                self.queue.put(None)

    def work(self, bot, sendto):
        if bot.opener is None:
            return
        while True:
            name = self.queue.get()
            if name is None:
                bot.getMapInfo()
                print(bot.login, 'finished')
                for i in bot.map.values():
                    if i[0].lower() == bot.login:
                        #bot.giveAll(sendto)
                        bot.logout()
                        return
                bot.logout()
                return
            bot.getMapInfo()
            bot.conquerCountry(name)

countries = dict(i.strip().split(maxsplit=1) for i in open('countries.txt', encoding='utf-8') if i)
try:
    proxy = open('proxy.txt').read().strip().splitlines()
except Exception:
    proxy = []

def main():
    lp = [i.split() for i in open('accounts.txt') if i.strip() and i[0] != '#']
    if len(proxy) + 1 < len(lp):
        print('Not enough proxies')
        sys.exit(1)
    logins = {i[0].lower() for i in lp}
    bm = BotManager(lp)
    mainbot = bm.bots[0]
    users = {i[0] for i in mainbot.map.values()}
    users = [(i, sum(mainbot.map[j][0] == i for j in mainbot.map), mainbot.user_to_frac[i]) for i in users]
    print('Users on the map:' , ', '.join('{0}:{2} ({1})'.format(*i) for i in sorted(users, key=lambda x:-x[1])))
    c = input('Enter countries or users to conquer: ').lower().split()
    bm.conquer(c)


if __name__ == '__main__':
    main()

