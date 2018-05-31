#!/usr/bin/env python3

import requests
import json
import time
import random
import sys
import re
import traceback
from collections import defaultdict

ROLL_INTERVAL = 5
USER_AGENT = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/53.0.2763.0 Safari/537.36'
HOST = 'https://worldroulette.ru/'


class Map:

    def __init__(self, me):
        self.country_names = {}
        self.cached_max_level = {}
        self.me = me

    def addMap(self, data):
        if not data.startswith('jQuery.fn.vectorMap('):
            return
        data = data.replace('jQuery.fn.vectorMap(', '[').replace(');', ']').replace("'", '"')
        data = json.loads(data)[2]['paths']
        self.country_names.update({i: data[i]['name'] for i in data})

    def updateState(self, data):
        self.world_state = {}
        for name, state in data['map'].items():
            self.world_state[name] = (str(state['uid']), state['sp'])
        self.players = data['players']

    def _pointsToWin(self, country):
        if self.world_state[country][0] in self.me:
            return self.world_state[country][1] - 100
        else:
            return self.world_state[country][1]

    def sortedList(self):
        return sorted(self.world_state, key=self._pointsToWin)

    def getPlayerList(self):
        countries = defaultdict(int)
        points = defaultdict(int)
        for name, value in self.world_state.items():
            countries[value[0]] += 1
            points[value[0]] += value[1]
        users = [{'id': i, 'name': self.players[i]['name'], 'countries': countries[i], 'points': points[i]}
                 for i in self.players if points[i]]
        return sorted(users, key=lambda x: (-x['countries'], -x['points'], x['id']))

    def isMine(self, region):
        return self.world_state[region][0] in self.me

    def getLevel(self, region):
        return self.world_state[region][1]

    def getOwner(self, region, id=False):
        if id:
            return self.world_state[region][0]
        else:
            return self.players[self.world_state[region][0]]['name']

    def updateMaxLevel(self, region):
        self.cached_max_level[region] = self.getLevel(region)


class SessionManager:

    def __init__(self, sessions):
        self.sessions = sessions
        self.auth()

    def auth(self):
        self.openers = []
        self.ids = []
        for session in self.sessions:
            self.openers.append(requests.session())
            self.openers[-1].cookies['session'] = session
            me = json.loads(self.open('getthis', {}, opener=-1))
            if not me:
                print('Invalid session:', session)
                sys.exit(-1)
            self.ids.append(str(list(me)[0]))
        data = self.open('getplayers?ids=[{}]'.format('%2C'.join(self.ids)), opener=0)
        names = json.loads(data)
        self.names = [names[id]['name'] for id in self.ids]

    def open(self, uri, params=None, opener=None):
        headers = {'Connection': None, 'User-agent': USER_AGENT}
        if params is not None:
            params = json.dumps(params).encode()
        for i in range(10):
            try:
                if params is None:
                    if opener is None:
                        resp = requests.get(HOST + uri, headers=headers)
                    else:
                        resp = self.openers[opener].get(HOST + uri, headers=headers)
                else:
                    headers['Content-type'] = 'application/json'
                    if opener is None:
                        resp = requests.post(HOST + uri, headers=headers, data=params)
                    else:
                        resp = self.openers[opener].post(HOST + uri, headers=headers, data=params)
                resp.encoding = 'UTF-8'
                return resp.text
            except Exception as e:
                self.auth()
        return ''



class Bot:

    def __init__(self, sessions):
        self.conn = SessionManager(sessions)
        self.order = 'm'
        self.last_roll = 0
        resp = ''
        self.map = Map(self.conn.ids)
        for name in self.getMapFilenames():
            self.map.addMap(self.open(name))
        self.getMapInfo()
        self.last_error = {}

    def open(self, *args, **kwargs):
        return self.conn.open(*args, **kwargs)

    def getMapFilenames(self):
        page = self.open('', opener=0)
        maps = re.findall(r'<script src="/([a-z-]*map[a-z-]*.js)"></script>', page)
        return maps

    def getMapInfo(self):
        try:
            data = self.open('get')
            pg = json.loads(data)
        except Exception:
            traceback.print_exc()
            time.sleep(1)
            self.getMapInfo()
            return
        self.map.updateState(pg)


    def fight(self, country):
        try:
            d = {'target': country, 'captcha': ''}
            ctime = time.time()
            if ctime < self.last_roll + ROLL_INTERVAL:
                time.sleep(self.last_roll + ROLL_INTERVAL - ctime)
            self.last_roll = ctime
            for i in range(len(self.conn.ids)):
                res = self.open('roll', d, opener=i)
                if not res:
                    continue
                res = json.loads(res)
                if res['result'] != 'error':
                    self.last_error[i] = None
                if res['result'] == 'success':
                    combo = 1
                    num = re.search(r'\d{4}', res['data']).group(0)
                    if num[-2] == num[-3]:
                        combo = 2
                        if num[-4] == num[-3]:
                            combo = 3
                    print('.*#@'[combo], end='', flush=True)
                    if 'вы успешно захватили' in res['data']:
                        print('Conquered')
                        return 'done'
                elif res['result'] == 'note' and 'уже улучшена' in res['data']:
                    print('Finished')
                    self.getMapInfo()
                    self.map.updateMaxLevel(country)
                    return 'max'
                elif res['result'] == 'fail':
                    print('.', end='', flush=True)
                elif res['result'] == 'error':
                    if res['data'] != self.last_error.get(i) and res['data'] != 'Подождите немного!':
                        print('[{} - {}]'.format(self.conn.names[i], res['data']), end='', flush=True)
                    self.last_error[i] = res['data']
                self.getMapInfo()
        except Exception as e:
            traceback.print_exc()
            time.sleep(1)
            self.getMapInfo()
            return 'error'

    def conquerCountry(self, country):
        if self.map.isMine(country):
            return False
        print('\nConquering {} ({}), level {}, belongs to {}'.format(country, self.map.country_names[country],
                                                                     self.map.getLevel(country),
                                                                     self.map.getOwner(country)))
        while not self.map.isMine(country):
            self.fight(country)
        self.sendToBatya(country)
        return True

    def empowerCountry(self, country):
        if not self.map.isMine(country) or self.map.getLevel(country) >= self.map.cached_max_level.get(country, 10):
            return False
        print('\nEmpowering {} ({}), level {}'.format(country, self.map.country_names[country], self.map.getLevel(country)))
        while True:
            if self.fight(country) == 'max':
                return True

    def conquer(self, object_list):
        self.getMapInfo()
        while True:
            tmap = self.map.sortedList()
            changed = 0
            for name in tmap:
                if name in object_list or name[:2] in object_list or self.map.getOwner(name, True) in object_list or '*' in object_list:
                    if self.order == 'e':
                        changed += self.empowerCountry(name)
                    elif self.order == 'c':
                        changed += self.conquerCountry(name)
                    else:
                        changed += self.conquerCountry(name)
                        changed +=self.empowerCountry(name)
                    if changed:
                        break
            else:
                return
            if not changed:
                return

    def sendToBatya(self, country):
        pname = self.map.getOwner(country, True)
        if pname not in self.conn.ids:
            return
        pid = self.conn.ids.index(pname)
        if pid == 0:
            return
        self.open('give', {'target': country, 'targetplid': self.conn.ids[0]}, opener=pid)

    def sendAll(self, uid):
        self.getMapInfo()
        for c in self.map.sortedList():
            self.sendToBatya(c)
        self.getMapInfo()
        count = 0
        for c in self.map.sortedList():
            if not self.map.isMine(c, True):
                continue
            if uid == 'random':
                res = ''
                while not res.startswith('Территория'):
                    res = self.open('give', {'target': c, 'targetplid': random.randint(1, 3000)}, opener=0)
            else:
                res = self.open('give', {'target': c, 'targetplid': uid}, opener=0)
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
        bot.order = 'c'
        bot.conn.auth()
        for i in bot.last_error:
            bot.last_error[i] = None
        bot.getMapInfo()
        print('Users on the map:\n' + '\n'.join('[{id:4}] {name} ({countries}, {points})'.format(**i) for i in bot.map.getPlayerList()))
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
        if c and len(c[0]) == 1 and c[0] in 'eca':
            bot.order = c[0]
            c = c[1:]
        c = list(map(str.upper, c))
        if not c:
            c = ['*']
        bot.getMapInfo()
        try:
            for country in bot.map.sortedList():
                bot.sendToBatya(country)
            bot.conquer(c)
            print()
        except KeyboardInterrupt:
            print('Interrupting')
            continue


if __name__ == '__main__':
    main()
