#!/usr/bin/python3

import requests
import hyper.contrib
import json
import time
import random
import sys

ROLL_INTERVAL = 5
USER_AGENT = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/53.0.2763.0 Safari/537.36'


class Bot:
    host = 'https://worldroulette.ru/'

    def __init__(self, session):
        self.session = session
        self.auth()
        try:
            self.login = json.loads(self.open('getthis', {}))['name']
            self.getMapInfo()
        except Exception:
            print('The server is down')
            sys.exit(1)

    def sorted_map(self):
        return sorted(self.map, key=lambda x:(-self.map[x][3] / self.map[x][1], x))

    def auth(self):
        self.opener = requests.session()
        self.opener.mount(self.host, hyper.contrib.HTTP20Adapter())
        self.opener.cookies['session'] = self.session


    def genCode(self, country):
        r = random.random()
        a = 'rand' + country + str(r)
        b = 0
        for i in a:
            b *= 31
            b += ord(i)
            while b < -2**31:
                b += 2**32
            while b > 2 ** 31 - 1:
                b -= 2**32
        return {'a': b, 'b': r}

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
            print(e)
            self.auth()
            return ''

    def getMapInfo(self):
        pg = json.loads(self.open('gethint', {}).replace('\n', ' ').strip())
        self.user_to_frac = {}
        self.map = {}
        for i in pg:
            self.user_to_frac[pg[i]['User']] = pg[i]['Faction'] or '<none>'
            self.map[i] = (pg[i]['User'], pg[i]['sp'], pg[i]['Faction'] or '<none>', float(pg[i]['relsize']))

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
        print('Conquering {} ({}), level {}, belongs to {}'.format(country, countries[country], self.map[country][1], self.map[country][0]))
        while not self.fight(country):
            pass

    def conquer(self, object_list):
        tmap = self.sorted_map()
        for name in tmap:
            if name.lower() in object_list or self.map[name][0].lower() in object_list or '*' in object_list:
                if self.map[name][0].lower() == self.login:
                    continue
                self.conquerCountry(name)
                self.getMapInfo()

countries = dict(i.strip().split(maxsplit=1) for i in open('countries.txt', encoding='utf-8') if i)

def main():
    session = open('accounts.txt').read().strip()
    bot = Bot(session)
    users = {i[0] for i in bot.map.values()}
    users = [(i, sum(bot.map[j][0] == i for j in bot.map), bot.user_to_frac[i]) for i in users]
    print('Users on the map:' , ', '.join('{0}:{2} ({1})'.format(*i) for i in sorted(users, key=lambda x:-x[1])))
    c = input('Enter countries or users to conquer: ').lower().split()
    bot.conquer(c)


if __name__ == '__main__':
    main()
