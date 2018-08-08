#!/usr/bin/env python3

import argparse
import requests
import json
import time
import random
import sys
import re
import traceback
import os
import subprocess
from collections import defaultdict
from functools import partial

CAPTCHA_WAIT_INTERVAL = 25
ROLL_INTERVAL = 1.1
USER_AGENT = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/53.0.2763.0 Safari/537.36'
HOST = 'https://worldroulette.ru/'
MAX_LEVEL = 3


def parse_args():
    parser = argparse.ArgumentParser(description='Bot for worldroulette.ru')
    parser.add_argument('sessions', nargs='*', help='session cookies from your browser')
    parser.add_argument('-c', '--captcha', action='store_true', help='always captcha warnings')
    return parser.parse_args()

args = parse_args()

class Map:

    def __init__(self, me):
        self.country_names = {}
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
        countries = list(self.world_state)
        random.shuffle(countries)
        return sorted(countries, key=self._pointsToWin)

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


class Roller:

    def __init__(self, open_proc):
        self.open_proc = open_proc
        self.last_roll = 0
        self.last_non_captcha = 0
        self.last_error = None

    def roll(self, target):
        now = time.time()
        if now < self.last_roll + ROLL_INTERVAL:
            time.sleep(self.last_roll + ROLL_INTERVAL - now)
        self.last_roll = time.time()

        data = {'target': target}
        res = self.open_proc('roll', data)
        if not res:
            return ''
        res = json.loads(res)
        if res['result'] == 'error':
            if res['data'].startswith('ReCaptcha') and not args.captcha and time.time() < self.last_non_captcha + CAPTCHA_WAIT_INTERVAL:
                return ''
            if res['data'].startswith('Подождите немного'):
                return ''
            if res['data'] != self.last_error:
                self.last_error = res['data']
                return 'error'
            return ''
        else:
            self.last_error = None
            self.last_non_captcha = time.time()
            if res['result'] == 'success':
                combo = 1
                num = re.search(r'\d{4}', res['data']).group(0)
                if num[-2] == num[-3]:
                    combo = 2
                    if num[-4] == num[-3]:
                        combo = 3
                print('.*#@'[combo], end='', flush=True)
                if 'вы успешно захватили' in res['data']:
                    return 'done'
            elif res['result'] == 'note' and 'уже улучшена' in res['data']:
                return 'max'
            elif res['result'] == 'fail':
                print('.', end='', flush=True)
                return 'fail'


def lookup_factions(ids, players, open_proc):
    factions = {i: players[i].get('fid') or None for i in ids if i in players}
    remaining = [i for i in ids if i not in players]
    if remaining:
        res = json.loads(open_proc('getplayers?ids=[' + ','.join(remaining) + ']'))
        factions.update({i: res[i].get('fid') or None for i in remaining})
    return factions


class Bot:

    def __init__(self, sessions):
        self.conn = SessionManager(sessions)
        self.order = 'm'
        self.map = Map(self.conn.ids)
        self.rollers = [Roller(partial(self.conn.open, opener=i)) for i in range(len(self.conn.ids))]
        self.map.addMap(self.open('world_mill_ru.js'))
        self.getMapInfo()

    def open(self, *args, **kwargs):
        return self.conn.open(*args, **kwargs)

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

    def getOnline(self):
        data = self.open('online', opener=0)
        return list(map(str, json.loads(data)['online']))

    def fight(self, country):
        try:
            for num, roller in enumerate(self.rollers):
                res = roller.roll(country)
                if res == 'error':
                    print('[{} - {}]'.format(self.conn.names[num], roller.last_error), end='', flush=True)
                elif res == 'done':
                    print('Conquered', flush=True)
        except Exception as e:
            traceback.print_exc()
            time.sleep(1)
        self.getMapInfo()

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
        if not self.map.isMine(country) or self.map.getLevel(country) >= MAX_LEVEL:
            return False
        print('\nEmpowering {} ({}), level {}'.format(country, self.map.country_names[country], self.map.getLevel(country)))
        while self.map.getLevel(country) < MAX_LEVEL:
            self.fight(country)
        print()
        return True


    def matches(self, country, object_list, online_with_factions):
        for item in object_list:
            if item == '*' or country.startswith(item.upper()) or self.map.country_names[country].upper().startswith(item.upper()):
                return True
            if item == self.map.getOwner(country, True) or self.map.getOwner(country).upper().startswith(item.upper()):
                return True
            if item.upper() == 'OFFLINE':
                if self.map.isMine(country):
                    return True
                owner = self.map.getOwner(country, True)
                if owner in online_with_factions:
                    return False
                if self.map.players[owner].get('fid') not in filter(bool, online_with_factions.values()):
                    return True
        return False

    def conquer(self, object_list):
        self.getMapInfo()
        for roller in self.rollers:
            roller.last_error = None
        while True:
            tmap = self.map.sortedList()
            changed = 0
            online_list = self.getOnline()
            online_with_factions = lookup_factions(online_list, self.map.players, partial(self.conn.open, opener=0))
            for name in tmap:
                if self.matches(name, object_list, online_with_factions):
                    if self.order == 'e':
                        changed += self.empowerCountry(name)
                    elif self.order == 'c':
                        changed += self.conquerCountry(name)
                    else:
                        changed += self.conquerCountry(name)
                        changed += self.empowerCountry(name)
                    if changed:
                        break
            else:
                return
            if not changed:
                return

    def sendToBatya(self, country, force=False):
        pname = self.map.getOwner(country, True)
        if pname not in self.conn.ids:
            return
        pid = self.conn.ids.index(pname)
        if pid == 0 and not force:
            return
        self.open('give', {'target': country, 'targetplid': self.conn.ids[0]}, opener=pid)

    def sendAll(self, uid):
        self.getMapInfo()
        for c in self.map.sortedList():
            self.sendToBatya(c)
        self.getMapInfo()
        count = 0
        for c in self.map.sortedList():
            if not self.map.isMine(c):
                continue
            if uid == 'random':
                res = ''
                while 'теперь принадлежит' not in res:
                    res = self.open('give', {'target': c, 'targetplid': random.randint(1, 3000)}, opener=0)
            else:
                res = self.open('give', {'target': c, 'targetplid': uid}, opener=0)
            print(res)
            count += 1
        print('Countries given:', count)
        self.getMapInfo()

    def laser(self, object_list):
        updated = 0
        while True:
            now = time.time()
            if now - updated > 15:
                self.getMapInfo()
                updated = now
            for country in self.map.world_state:
                if self.map.isMine(country) and self.matches(self, object_list, []):
                    self.sendToBatya(country, force=True)



def main():
    if args.sessions:
        sessions = args.sessions
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
        bot.order = 'a'
        bot.conn.auth()
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
        if c and c[0] == 'laser':
            if len(c) != 2:
                print('What to laser?\n')
                continue
            try:
                bot.laser(c[1:])
            except KeyboardInterrupt:
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
