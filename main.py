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

    def __init__(self, sessions):
        self.sessions = sessions
        self.auth()
        self.order = 'm'
        self.last_roll = 0
        resp = ''
        try:
            self.logins = []
            self.ids = []
            for i in range(len(self.openers)):
                resp = self.open('getthis', {}, opener=i)
                self.logins.append(json.loads(resp)['name'])
                self.ids.append(json.loads(resp)['id'])
            self.fetchCountryNames()
            self.getMapInfo()
            self.last_error = dict.fromkeys(self.logins)
        except Exception as e:
            print(resp or 'The server is down!')
            sys.exit(1)

    def fetchCountryNames(self):
        s = self.open('jquery-jvectormap-world-mill-ru.js').replace('jQuery.fn.vectorMap(', '[').replace(');', ']').replace("'", '"')
        d = json.loads(s)[2]['paths']
        self.country_name = {i: d[i]['name'] for i in d}

    def sorted_map(self):
        func = {'m': lambda x: -self.map[x][3] / self.map[x][1],
                'M': lambda x: self.map[x][3] / self.map[x][1],
                'l': lambda x: self.map[x][1],
                'L': lambda x: -self.map[x][1],
                's': lambda x: -self.map[x][3],
                'S': lambda x: self.map[x][3],
                'e': lambda x: -self.map[x][3],}
        return sorted(self.map, key=lambda x:(func[self.order](x), x))

    def auth(self):
        self.openers = []
        for session in self.sessions:
            self.openers.append(requests.session())
            self.openers[-1].mount(self.host, hyper.contrib.HTTP20Adapter())
            self.openers[-1].cookies['session'] = session


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

    def open(self, uri, params=None, opener=0):
        headers = {'Connection': None, 'User-agent': USER_AGENT}
        for i in range(10):
            try:
                if params is None:
                    resp = self.openers[opener].get(self.host + uri, headers=headers)
                else:
                    if isinstance(params, str):
                        headers['Content-type'] = 'application/json'
                    resp = self.openers[opener].post(self.host + uri, headers=headers, data=params)
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

    def fight(self, country):
        try:
            d = self.genCode(country)
            d['target'] = country
            d['captcha'] = ''
            ctime = time.time()
            if ctime < self.last_roll + ROLL_INTERVAL:
                time.sleep(self.last_roll + ROLL_INTERVAL - ctime)
            self.last_roll = ctime
            for i in range(len(self.openers)):
                res = self.open('roll', json.dumps(d), opener=i)
                if not res:
                    continue
                res = json.loads(res)
                if res['result'] != 'error':
                    self.last_error[i] = None
                if res['result'] == 'success':
                    try:
                        num = re.search(r'\d{5}', res['data']).group(0)
                        combo = num[-2] == num[-3]
                    except Exception as e:
                        print(e)
                        combo = False
                    print('#' if combo else '*', end='', flush=True)
                    if 'вы успешно захватили' in res['data']:
                        print('Conquered')
                        return
                    else:
                        self.getMapInfo()
                        if self.map[country][0] in self.logins:
                            if self.map[country][1] == 7:
                                print('Finished')
                                return
                elif res['result'] == 'fail':
                    print('.', end='', flush=True)
                elif res['result'] == 'error':
                    if res['data'] != self.last_error[i] and res['data'] != 'Подождите немного!':
                        print('[{} - {}]'.format(self.logins[i], res['data']), end='', flush=True)
                    self.last_error[i] = res['data']
                self.getMapInfo()
        except Exception as e:
            print(e)
            time.sleep(1)
            return False

    def conquerCountry(self, country):
        if self.map[country][0].lower() in self.logins:
            return
        print('\nConquering {} ({}), level {}, belongs to {}'.format(country, self.country_name[country], self.map[country][1], self.map[country][0]))
        while self.map[country][0].lower() not in self.logins:
            self.fight(country)
        self.sendToBatya(country)

    def empowerCountry(self, country):
        if self.map[country][1] == 7 or self.map[country][0].lower() not in self.logins:
            return
        print('\nEmpowering {} ({}), level {}'.format(country, self.country_name[country], self.map[country][1]))
        while self.map[country][1] != 7:
            self.fight(country)

    def conquer(self, object_list):
        self.getMapInfo()
        tmap = self.sorted_map()
        for name in tmap:
            if name.lower() in object_list or self.map[name][0].lower() in object_list or '*' in object_list:
                if self.order == 'e':
                    self.empowerCountry(name)
                else:
                    self.conquerCountry(name)
                    self.empowerCountry(name)

    def sendToBatya(self, country):
        pname = self.map[country][0]
        if pname not in self.logins:
            return
        pid = self.logins.index(pname)
        if pid == 0:
            return
        self.open('give', json.dumps({'target': country, 'targetplid': self.ids[0]}), opener=pid)

def main():
    if len(sys.argv) > 1:
        sessions = sys.argv[1:]
        with open('accounts.txt', 'w') as f:
            f.write(' '.join(sessions))
    else:
        try:
            sessions = open('accounts.txt').read().split()
        except FileNotFoundError:
            print('accounts.txt does not exist')
            sys.exit()
    bot = Bot(sessions)
    while True:
        bot.order = 'm'
        for i in bot.last_error:
            bot.last_error[i] = None
        users = bot.getPlayerList()
        users = [(i['name'], sum(bot.map[j][0] == i['name'] for j in bot.map), i['clan'] or '<none>', i['id'],
                  sum(bot.map[j][1] * (bot.map[j][0] == i['name']) for j in bot.map)) for i in users]
        print('Users on the map:\n' + '\n'.join('[{3:3}] {0}:{2} ({1}, {4})'.format(*i) for i in sorted(users, key=lambda x:(-x[1], -x[4]))))
        print()
        c = input('Enter countries or users to conquer: ').split()
        id_to_name = {i[3]: i[0].lower() for i in users}
        if c and len(c[0]) == 1 and c[0] in 'lLsSmMe':
            bot.order = c[0]
            c = c[1:]
        if not c:
            c = ['*']
        c = [id_to_name.get(int(i)) if i.isdigit() else i.lower() for i in c]
        for country in bot.map:
            bot.sendToBatya(country)
        bot.conquer(c)
        print()


if __name__ == '__main__':
    main()
