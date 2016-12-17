#!/usr/bin/python3

import requests
import hyper.contrib
import json
import time
import random
import sys
import re

ROLL_INTERVAL = 5
USER_AGENT = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/53.0.2763.0 Safari/537.36'


class Bot:
    host = 'https://worldroulette.ru/'

    def __init__(self, session):
        self.session = session
        self.auth()
        self.order = 'm'
        resp = ''
        try:
            resp = self.open('getthis', {})
            self.login = json.loads(resp)['name']
            self.getMapInfo()
        except Exception as e:
            print(resp or 'The server is down!')
            sys.exit(1)

    def sorted_map(self):
        func = {'m': lambda x: -self.map[x][3] / self.map[x][1],
                'M': lambda x: self.map[x][3] / self.map[x][1],
                'l': lambda x: self.map[x][1],
                'L': lambda x: -self.map[x][1],
                's': lambda x: -self.map[x][3],
                'S': lambda x: self.map[x][3],}
        return sorted(self.map, key=lambda x:(func[self.order](x), x))

    def auth(self):
        self.opener = requests.session()
        self.opener.mount(self.host, hyper.contrib.HTTP20Adapter())
        self.opener.cookies['session'] = self.session


    def genCode(self, country):
        r = random.random()
        a = 'cyka' + country + str(r)
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
        for i in range(10):
            try:
                if params is None:
                    resp = self.opener.get(self.host + uri, headers=headers)
                else:
                    if isinstance(params, str):
                        headers['Content-type'] = 'application/json'
                    resp = self.opener.post(self.host + uri, headers=headers, data=params)
                resp.encoding = 'UTF-8'
                return resp.text
            except Exception as e:
                time.sleep(1)
                self.auth()
        return ''

    def getMapInfo(self):
        pg = json.loads(self.open('gethint', {}))
        self.map = {}
        for i in pg:
            self.map[i] = (pg[i]['User'], pg[i]['sp'], pg[i]['Faction'] or '<none>', float(pg[i]['relsize']))

    def getPlayerList(self):
        res = self.open('getplayers')
        pg = json.loads(res)
        all_users = {i[0] for i in self.map.values()}
        res = []
        for i in pg:
            for j in all_users:
                if i['name'].startswith(j):
                    i['name'] = j
                    res.append(i)
                    break
        return res

    def fight(self, country, last_error='', empower=False):
        try:
            d = self.genCode(country)
            d['target'] = country
            d['captcha'] = ''
            res = self.open('roll', json.dumps(d))
            time.sleep(ROLL_INTERVAL)
            if not res:
                return self.fight(country, empower=empower)
            res = json.loads(res)
            if res['result'] == 'success':
                if 'вы успешно захватили' in res['data']:
                    print('Conquered')
                    return True
                else:
                    try:
                        num = re.search(r'\d{5}', res['data']).group(0)
                        combo = num[-2] == num[-3]
                    except Exception as e:
                        print(e)
                        combo = False
                    print('#' if combo else '*', end='', flush=True)
                    self.getMapInfo()
                    if self.map[country][0] == self.login:
                        if empower:
                            if self.map[country][1] == 7:
                                print('Finished')
                                return True
                            else:
                                return False
                        else:
                            return True
                    return False
            elif res['result'] == 'fail':
                print('.', end='', flush=True)
                return False
            elif res['result'] == 'error':
                if res['data'] != last_error and res['data'] != 'Подождите немного!':
                    print('[{}]'.format(res['data']), end='', flush=True)
                return self.fight(country, res['data'], empower=empower)
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

    def empowerCountry(self, country):
        if self.map[country][1] == 7:
            return
        print('Empowering {} ({}), level {}'.format(country, countries[country], self.map[country][1]))
        while not self.fight(country, empower=True):
            pass

    def conquer(self, object_list):
        tmap = self.sorted_map()
        for name in tmap:
            if name.lower() in object_list or self.map[name][0].lower() in object_list or '*' in object_list:
                if self.map[name][0].lower() == self.login:
                    self.empowerCountry(name)
                else:
                    self.conquerCountry(name)
                self.getMapInfo()

countries = dict(i.strip().split(maxsplit=1) for i in open('countries.txt', encoding='utf-8') if i)

def main():
    if len(sys.argv) > 1:
        session = sys.argv[1]
        with open('accounts.txt', 'w') as f:
            f.write(session)
    else:
        try:
            session = open('accounts.txt').read().strip()
        except FileNotFoundError:
            print('accounts.txt does not exist')
            sys.exit()
    bot = Bot(session)
    users = bot.getPlayerList()
    users = [(i['name'], sum(bot.map[j][0] == i['name'] for j in bot.map), i['clan'] or '<none>', i['id'],
              sum(bot.map[j][1] * (bot.map[j][0] == i['name']) for j in bot.map)) for i in users]
    print('Users on the map:\n' + '\n'.join('[{3:3}] {0}:{2} ({1}, {4})'.format(*i) for i in sorted(users, key=lambda x:-x[1])))
    print()
    c = input('Enter countries or users to conquer: ').split()
    id_to_name = {i[3]: i[0].lower() for i in users}
    if c and len(c[0]) == 1 and c[0] in 'lLsSmM':
        bot.order = c[0]
        c = c[1:]
    c = [id_to_name[int(i)] if i.isdigit() else i.lower() for i in c]
    bot.conquer(c)


if __name__ == '__main__':
    main()
