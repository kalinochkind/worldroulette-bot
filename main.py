#!/usr/bin/python3

import requests
import hyper.contrib
import json
import time
import random
import sys
import re

ROLL_INTERVAL = 5
MAX_LEVEL = 3
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
            self.ids = []
            self.player_cache = {}
            for i in range(len(self.openers)):
                resp = self.open('getthis', {}, opener=i)
                self.ids.append(str(json.loads(resp)))
            self.fetchCountryNames()
            self.fractions = json.loads(self.open('factions'))
            self.fractions['0'] = {'name': '<none>'}
            self.getMapInfo()
            self.getPlayers(self.ids)
            self.last_error = {}
        except Exception as e:
            print(resp or 'The server is down!')
            sys.exit(1)

    def fetchCountryNames(self):
        s = self.open('jquery-jvectormap-world-mill-ru.js').replace('jQuery.fn.vectorMap(', '[').replace(');', ']').replace("'", '"')
        d = json.loads(s)[2]['paths']
        self.country_name = {i: d[i]['name'] for i in d}

    def getPlayers(self, players):
        players = [i for i in map(str, players) if i not in self.player_cache]
        if players:
            resp = self.open('getplayers?ids=[{}]'.format('%2C'.join(players)))
            pg = json.loads(resp)
            for i in pg:
                pg[i]['fid'] = str(pg[i].get('fid', 0))
                pg[i]['id'] = str(pg[i]['id'])
            self.player_cache.update(pg)

    def sorted_map(self):
        func = {'m': lambda x: self.map[x][1],
                'M': lambda x: -self.map[x][1],
                'e': lambda x: self.map[x][1],
                'c': lambda x: self.map[x][1],}
        return sorted(self.map, key=lambda x:(func[self.order](x), x))

    def auth(self):
        self.openers = []
        for session in self.sessions:
            self.openers.append(requests.session())
            self.openers[-1].mount(self.host, hyper.contrib.HTTP20Adapter())
            self.openers[-1].cookies['session'] = session

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
        pg = json.loads(self.open('get', {}))
        self.map = {}
        for i in pg['map']:
            self.map[i] = (str(pg['map'][i]['uid']), pg['map'][i]['sp'])
        users = pg['players']
        for i in users:
            users[i]['id'] = str(users[i]['id'])
            users[i]['fid'] = str(users[i].get('fid', 0))
        self.player_cache.update(users)

    def getPlayerList(self):
        all_users = {i[0] for i in self.map.values()}
        return [self.player_cache[i] for i in all_users]

    def fight(self, country):
        try:
            d = {'target': country, 'captcha': ''}
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
                    combo = 0
                    try:
                        num = re.search(r'\d{5}', res['data']).group(0)
                        if num[-2] == num[-3]:
                            combo = 1
                            if num[-4] == num[-3]:
                                combo = 2
                    except Exception as e:
                        print(e)
                    print('*#@'[combo], end='', flush=True)
                    if 'вы успешно захватили' in res['data']:
                        print('Conquered')
                        return
                    else:
                        self.getMapInfo()
                        if self.map[country][0] in self.ids:
                            if self.map[country][1] >= MAX_LEVEL:
                                print('Finished')
                                return
                elif res['result'] == 'fail':
                    print('.', end='', flush=True)
                elif res['result'] == 'error':
                    if res['data'] != self.last_error.get(i) and res['data'] != 'Подождите немного!':
                        print('[{} - {}]'.format(self.player_cache[self.ids[i]]['name'], res['data']), end='', flush=True)
                    self.last_error[i] = res['data']
                self.getMapInfo()
        except Exception as e:
            print(e)
            time.sleep(1)
            return False

    def conquerCountry(self, country):
        if self.map[country][0] in self.ids:
            return
        print('\nConquering {} ({}), level {}, belongs to {}'.format(country, self.country_name[country], self.map[country][1], self.player_cache[self.map[country][0]]['name']))
        while self.map[country][0].lower() not in self.ids:
            self.fight(country)
        self.sendToBatya(country)

    def empowerCountry(self, country):
        if self.map[country][1] >= MAX_LEVEL or self.map[country][0] not in self.ids:
            return
        print('\nEmpowering {} ({}), level {}'.format(country, self.country_name[country], self.map[country][1]))
        while self.map[country][1] < MAX_LEVEL:
            self.fight(country)

    def conquer(self, object_list):
        self.getMapInfo()
        tmap = self.sorted_map()
        for name in tmap:
            if name in object_list or self.map[name][0] in object_list or '*' in object_list:
                if self.order == 'e':
                    self.empowerCountry(name)
                elif self.order == 'c':
                    self.conquerCountry(name)
                else:
                    self.conquerCountry(name)
                    self.empowerCountry(name)

    def sendToBatya(self, country):
        pname = self.map[country][0]
        if pname not in self.ids:
            return
        pid = self.ids.index(pname)
        if pid == 0:
            return
        self.open('give', json.dumps({'target': country, 'targetplid': self.ids[0]}), opener=pid)

    def sendAll(self, uid):
        self.getMapInfo()
        for c in self.map:
            self.sendToBatya(c)
        count = 0
        for c in self.map:
            if self.map[c][0] != self.ids[0]:
                continue
            if uid == 'random':
                res = ''
                while not res.startswith('Территория'):
                    res = self.open('give', json.dumps({'target': c, 'targetplid': random.randint(1, 2000)}))
            else:
                res = self.open('give', json.dumps({'target': c, 'targetplid': uid}))
            print(res)
            count += 1
        print('Countries given:', count)
        self.getMapInfo()

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
        users = [(i['name'], sum(bot.map[j][0] == i['id'] for j in bot.map), bot.fractions[str(i.get('fid', 0))]['name'], i['id'],
                  sum(bot.map[j][1] * (bot.map[j][0] == i['id']) for j in bot.map)) for i in users]
        print('Users on the map:\n' + '\n'.join('[{3:3}] {0}:{2} ({1}, {4})'.format(*i) for i in sorted(users, key=lambda x:(-x[1], -x[4]))))
        print()
        try:
            c = input('Enter countries or users to conquer: ').split()
        except EOFError:
            print()
            return
        if c and c[0] == 'give':
            if len(c) != 2:
                print('Usage: give (UID|random)\n')
                continue
            bot.sendAll(c[1])
            print()
            continue
        if c and len(c[0]) == 1 and c[0] in 'Mmec':
            bot.order = c[0]
            c = c[1:]
        c = list(map(str.upper, c))
        if not c:
            c = ['*']
        bot.getMapInfo()
        try:
            for country in bot.map:
                bot.sendToBatya(country)
            bot.conquer(c)
            print()
        except KeyboardInterrupt:
            print('Interrupting')
            continue


if __name__ == '__main__':
    main()
