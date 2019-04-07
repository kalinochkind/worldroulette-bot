#!/usr/bin/env python3

import argparse
import json
import time
import random
import logging
import sys
import math
import os
import re
import traceback
import readline
import threading
from collections import defaultdict
from functools import partial

import requests
from socketIO_client import SocketIO
from chromehack import get_session_cookie


from utils import parse_map


logging.getLogger('socketIO-client').setLevel(logging.ERROR)

CAPTCHA_WAIT_INTERVAL = 25
ROLL_INTERVAL = 1.1
USER_AGENT = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/53.0.2763.0 Safari/537.36'
HOST = 'https://worldroulette.ru/'
MAX_LEVEL = 3

WS_HOST = 'https://socket.worldroulette.ru'
WS_PORT = 444

BUY_ITEM_ID = 3331
BUY_ITEM_COUNT = 2
GOOD_ITEM_NAME = 'Мешок с сокровищами'


def parse_args():
    parser = argparse.ArgumentParser(description='Bot for worldroulette.ru')
    parser.add_argument('sessions', nargs='*', help='session cookies from your browser')
    parser.add_argument('-i', '--no-items', action='store_true', help='disable item management')
    return parser.parse_args()

ARGS = parse_args()

with open('centroids.json') as f:
    CENTROIDS = json.load(f)
with open('neighbors.json') as f:
    NEIGHBORS = {k: set(v) for k, v in json.load(f).items()}



def find_distance(bases, point):
    if not bases:
        return float('inf')
    return min((i[0] - point[0]) ** 2 + (i[1] - point[1]) ** 2 for i in bases)


class CredentialsManager:

    def __init__(self):
        with open('accounts.txt') as f:
            self.session = f.read().strip()

    def update_session(self, session):
        self.session = session
        with open('accounts.txt', 'w') as f:
            f.write(session)

credentials = CredentialsManager()


class SocketListener:

    def __init__(self):
        self.generation = 0
        self.reconnect()

    def monitor(self, generation):
        sio = SocketIO(WS_HOST, WS_PORT, cookies={'session': credentials.session})
        while generation == self.generation:
            sio.wait(seconds=1)

    def reconnect(self):
        self.generation += 1
        self._thread = threading.Thread(target=self.monitor, args=(self.generation,), daemon=True)
        self._thread.start()


class Map:

    def __init__(self, me):
        self.country_names = {}
        self.country_areas = {}
        self.me = me
        self.world_state = {}
        self.players = {}

    def add_map(self, data):
        data = parse_map(data)
        self.country_names.update({i: data[i]['name'] for i in data})
        self.country_areas.update({i: float(data[i]['area']) for i in data})

    def update_state(self, data):
        self.world_state = {}
        for name, state in data['map'].items():
            self.world_state[name] = (str(state['uid']), state['sp'])
        self.players = data['players']

    def _points_to_win(self, country):
        if self.world_state[country][0] in self.me:
            return self.world_state[country][1] - 100
        return self.world_state[country][1]

    def sorted_list(self, order):
        countries = list(self.world_state)
        if order == 'near' or order == 'conn':
            mine = {c for c in countries if self.world_state[c][0] in self.me}
            not_mine = [c for c in countries if self.world_state[c][0] not in self.me]
            random.shuffle(not_mine)
            dists = sorted(((find_distance([CENTROIDS[i] for i in NEIGHBORS[c].intersection(mine)], CENTROIDS[c]), c) for c in not_mine),
                           key=lambda x: x[0])
            if order == 'conn':
                dists = [i for i in dists if math.isfinite(i[0])]
            return sorted(mine, key=self._points_to_win) + [i[1] for i in dists]
        if order == 'random':
            random.shuffle(countries)
            countries.sort(key=self._points_to_win)
        elif order == 'small':
            countries.sort(key=self.country_areas.get)
        elif order == 'large':
            countries.sort(key=self.country_areas.get, reverse=True)
        return countries

    def get_player_list(self):
        countries = defaultdict(int)
        points = defaultdict(int)
        for value in self.world_state.values():
            countries[value[0]] += 1
            points[value[0]] += value[1]
        users = [{'id': i, 'name': self.players[i]['name'], 'countries': countries[i], 'points': points[i]}
                 for i in self.players if points[i]]
        return sorted(users, key=lambda x: (-x['points'], -x['countries'], int(x['id'])))

    def is_mine(self, region):
        return self.world_state[region][0] in self.me

    def get_level(self, region):
        return self.world_state[region][1]

    def get_owner_name(self, region):
        return self.players[self.world_state[region][0]]['name']

    def get_owner_id(self, region):
        return self.world_state[region][0]


class SessionManager:

    def __init__(self):
        self._auth_attempts = 0
        self.auth()

    def auth(self):
        self._auth_attempts += 1
        if self._auth_attempts > 10:
            print('\nAuth failed')
            sys.exit(1)
        self.openers = [requests.session()]
        self.openers[-1].cookies['session'] = credentials.session
        me = json.loads(self.open('getthis', {}, opener=-1)).get('players')
        if not me:
            print('Invalid session:', credentials.session)
            new_session = get_session_cookie()
            if new_session is not None and new_session != credentials.session:
                print('Got session cookie from Chrome')
                credentials.update_session(new_session)
                self.auth()
                return
            sys.exit(-1)
        self.ids = [str(list(me)[0])]
        data = self.open('getplayers?ids=[{}]'.format('%2C'.join(self.ids)), opener=0)
        names = json.loads(data)['players']
        self.names = [names[id]['name'] for id in self.ids]
        self._auth_attempts = 0

    def open(self, uri, params=None, opener=None):
        headers = {'Connection': None, 'User-agent': USER_AGENT}
        if params is not None:
            params = json.dumps(params).encode()
        for _ in range(5):
            try:
                if params is None:
                    if opener is None:
                        resp = requests.get(HOST + uri, headers=headers, timeout=3)
                    else:
                        resp = self.openers[opener].get(HOST + uri, headers=headers, timeout=3)
                else:
                    headers['Content-type'] = 'application/json'
                    if opener is None:
                        resp = requests.post(HOST + uri, headers=headers, data=params, timeout=3)
                    else:
                        resp = self.openers[opener].post(HOST + uri, headers=headers, data=params, timeout=3)
                resp.encoding = 'UTF-8'
                return resp.text
            except Exception as e:
                time.sleep(1)
                self.auth()
        return ''


class ItemManager:


    def __init__(self, open_proc):
        self.open_proc = open_proc
        shopdata = json.loads(self.open_proc('shoplist'))
        self.price = shopdata[str(BUY_ITEM_ID)]['price']

    def adjust_items(self):
        if ARGS.no_items:
            return
        data = json.loads(self.open_proc('inventory'))
        balance = list(data['players'].values())[0]['balance']

        enabled = 0
        for item in data['items'].values():
            if item['baseitem']['id'] == BUY_ITEM_ID and item['enabled'] and item['uses'] >= 15:
                enabled += 1
            if item['baseitem']['name_ru'] == GOOD_ITEM_NAME:
                continue
            if item['baseitem']['laser_color'] and item['baseitem']['laser_color'] != '#FF0000':
                print('Setting laser color', item['baseitem']['laser_color'])
                self.open_proc('toggleItem', {'id': item['id']})
            old_balance = balance
            print('Selling', item['baseitem']['name_ru'], end=' ')
            self.open_proc('sellItem', {'id': item['id']})
            data = json.loads(self.open_proc('inventory'))
            balance = list(data['players'].values())[0]['balance']
            print('for', balance - old_balance, 'coins')

        while balance >= self.price:
            print('Buying another bag')
            self.open_proc('buyItem', {'id': BUY_ITEM_ID})
            data = json.loads(self.open_proc('inventory'))
            balance = list(data['players'].values())[0]['balance']

        if enabled < BUY_ITEM_COUNT:
            for item in data['items'].values():
                if item['baseitem']['id'] == BUY_ITEM_ID and not item['enabled']:
                    enabled += 1
                    print('Enabling a bag')
                    self.open_proc('toggleItem', {'id': item['id']})
                    if enabled >= BUY_ITEM_COUNT:
                        break



    @staticmethod
    def parse_stats(stats):
        stats = [i.split('=') for i in stats.split('&')]
        return {i[0]: float(i[1]) for i in stats}

    @staticmethod
    def apply_stats(stats, total_stats, negate=False):
        for i in stats:
            if negate:
                total_stats[i] -= stats[i]
            else:
                total_stats[i] += stats[i]

    def should_take(self, item_stats, total_stats):
        for stat in self.ACTIVE_STATS + self.PASSIVE_STATS:
            if item_stats.get(stat, 0) > 0 and total_stats[stat] < self.STAT_LIMIT.get(stat, 1.499):
                return True
        return False

class Roller:

    def __init__(self, open_proc, socket_listener):
        self.open_proc = open_proc
        self.last_roll = 0
        self.last_error = None
        self.listener = socket_listener

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
            if res['data'].startswith('Подождите немного'):
                return ''
            if res['data'].startswith('Ваш IP не был'):
                self.listener.reconnect()
                time.sleep(1)
                return ''
            if res['data'] != self.last_error:
                self.last_error = res['data']
                return 'error'
        else:
            self.last_error = None
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
        return ''


def lookup_factions(ids, players, open_proc):
    factions = {i: players[i].get('fid') or None for i in ids if i in players}
    remaining = [i for i in ids if i not in players]
    if remaining:
        res = json.loads(open_proc('getplayers?ids=[' + ','.join(remaining) + ']'))['players']
        factions.update({i: res[i].get('fid') or None for i in remaining})
    return factions


class CountryMatcher:

    def __init__(self, world_map):
        self.map = world_map

    @staticmethod
    def consume_negation(item):
        if item.startswith('-'):
            return True, item[1:]
        return False, item

    def matches_one(self, country, item, online_list, players):
        if country.startswith(item.upper()) or self.map.country_names[country].upper().startswith(item.upper()):
            return True
        if item == self.map.get_owner_id(country) or self.map.get_owner_name(country).upper().startswith(item.upper()):
            if item.upper() not in self.map.country_names:
                return True
        if item.upper() == 'OFFLINE':
            if self.map.is_mine(country):
                return True
            owner = self.map.get_owner_id(country)
            if owner in online_list:
                return False
            if self.map.players[owner].get('fid') not in filter(bool, online_list.values()):
                return True
        if item.startswith('<=') and item[2:].isdigit() and players.get(self.map.get_owner_id(country), 0) <= int(item[2:]):
            return True
        return False

    def matches(self, country, object_list, online_list, players):
        matched = False
        positive = False
        levels = [1, 2, 3]
        for item in object_list:
            if item.startswith('^'):
                if item[1:].isdigit():
                    levels = list(map(int, item[1:]))
                continue
            negate, item = self.consume_negation(item)
            if not negate:
                positive = True
            if self.matches_one(country, item, online_list, players):
                if negate:
                    return False
                else:
                    matched = True
        if self.map.get_level(country) not in levels:
            return False
        return matched or not positive


class Bot:

    def __init__(self):
        self.conn = SessionManager()
        self.mode = 'a'
        self.map = Map(self.conn.ids)
        self.matcher = CountryMatcher(self.map)
        self.rollers = [Roller(partial(self.conn.open, opener=i), SocketListener()) for i in range(len(self.conn.ids))]
        self.item_managers = [ItemManager(partial(self.conn.open, opener=i)) for i in range(len(self.conn.ids))]
        self.map.add_map(self.open('world_mill_ru.js'))
        self.update_map()

    def open(self, *args, **kwargs):
        return self.conn.open(*args, **kwargs)

    def update_map(self):
        try:
            data = self.open('get')
            pg = json.loads(data)
        except Exception:
            traceback.print_exc()
            time.sleep(1)
            self.update_map()
            return
        self.map.update_state(pg)

    def get_online(self):
        data = self.open('online', opener=0)
        return list(map(str, json.loads(data)['online']))

    def fight(self, country):
        try:
            for num, roller in enumerate(self.rollers):
                res = roller.roll(country)
                if res == 'error':
                    print('[{}]'.format(roller.last_error), end='', flush=True)
                elif res == 'done':
                    print('Conquered', flush=True)
        except Exception:
            traceback.print_exc()
            time.sleep(1)
        self.update_map()

    def conquer_country(self, country):
        if self.map.is_mine(country):
            return False
        print('\nConquering {} ({}), level {}, belongs to {}'.format(country, self.map.country_names[country],
                                                                     self.map.get_level(country),
                                                                     self.map.get_owner_name(country)))
        rolls = 0
        while not self.map.is_mine(country):
            self.fight(country)
            rolls += 1
            if rolls > 40:
                print('Too tired')
                self.adjust_items()
                return True
        self.send_to_batya(country)
        self.adjust_items()
        return True

    def empower_country(self, country):
        if not self.map.is_mine(country) or self.map.get_level(country) >= MAX_LEVEL:
            return False
        print('\nEmpowering {} ({}), level {}'.format(country, self.map.country_names[country],
                                                      self.map.get_level(country)))
        rolls = 0
        while self.map.get_level(country) < MAX_LEVEL:
            self.fight(country)
            rolls += 1
            if rolls > 40:
                print('Too tired')
                self.adjust_items()
                return True
        print()
        self.adjust_items()
        return True


    def list_countries(self, object_list, order):
        tmap = self.map.sorted_list(order)
        online_list = self.get_online()
        online_with_factions = lookup_factions(online_list, self.map.players, partial(self.conn.open, opener=0))
        players = self.map.get_player_list()
        players = {i['id']: i['countries'] for i in players}
        res = [name for name in tmap if self.matcher.matches(name, object_list, online_with_factions, players)]
        return res


    def conquer(self, object_list, order):
        self.update_map()
        for roller in self.rollers:
            roller.last_error = None
        while True:
            changed = 0
            for name in self.list_countries(object_list, order):
                if self.mode == 'e':
                    changed += self.empower_country(name)
                elif self.mode == 'c':
                    changed += self.conquer_country(name)
                else:
                    changed += self.conquer_country(name)
                    changed += self.empower_country(name)
                if changed:
                    break
            else:
                return
            if not changed:
                return

    def adjust_items(self):
        for mgr in self.item_managers:
            mgr.adjust_items()

    def send_to_batya(self, country, force=False):
        pname = self.map.get_owner_id(country)
        if pname not in self.conn.ids:
            return
        pid = self.conn.ids.index(pname)
        if pid == 0 and not force:
            return
        self.open('give', {'target': country, 'targetplid': self.conn.ids[0]}, opener=pid)

    def send_countries(self, uid, objects, order):
        self.update_map()
        for c in self.list_countries(objects, order):
            self.send_to_batya(c)
        self.update_map()
        count = 0
        current_user = 1
        for c in self.list_countries(objects, order):
            if not self.map.is_mine(c):
                continue
            players = {int(i[0]) for i in self.map.world_state.values()}
            res = ''
            while 'теперь принадлежит' not in res:
                if uid == 'random':
                    target = random.randint(1, 3000)
                    while target in players:
                        target = random.randint(1, 3000)
                    res = self.open('give', {'target': c, 'targetplid': target}, opener=0)
                elif uid == 'seq':
                    res = self.open('give', {'target': c, 'targetplid': current_user}, opener=0)
                    if 'игрока не существует' in res:
                        print('Fail', current_user)
                        current_user += 1
                else:
                    res = self.open('give', {'target': c, 'targetplid': uid}, opener=0)
                time.sleep(0.5)
            current_user += 1
            print(res)
            time.sleep(2)
            count += 1
            self.update_map()
        print('Countries given:', count)
        self.update_map()

    def wipe_chat(self, ts):
        while True:
            data = json.loads(self.open('chat?last=undefined', opener=0))
            min_ts = min(int(i) for i in data['chat'])
            if min_ts > ts:
                return
            self.open('write', {'msg': '/msg 0 a'}, opener=0)
            time.sleep(1)

    def find_user(self, s):
        start = 0
        s = s.lower()
        while True:
            users = json.loads(self.open('getplayers?ids=[{}]'.format(','.join(map(str, range(start, start + 100))))))['players']
            for uid, user in users.items():
                if s in user['name'].lower():
                    print(uid, user['name'])
            start += 100
            if not users:
                return



ORDERS = ['near', 'conn', 'random', 'large', 'small']

def main():
    if ARGS.sessions:
        credentials.update_session(ARGS.sessions[0])
    bot = Bot()
    order = ORDERS[0]
    while True:
        bot.mode = 'a'
        bot.conn.auth()
        bot.update_map()
        bot.adjust_items()
        print('Users on the map:\n' + '\n'.join('[{id:4}] {name} ({countries}, {points})'.format(**i)
                                                for i in bot.map.get_player_list()))
        print()
        try:
            c = input('({})> '.format(order)).split()
        except EOFError:
            print()
            return
        if not c:
            continue
        try:
            if c[0] == 'wipe':
                if len(c) != 2 or not c[1].isdigit():
                    print('Timestamp required')
                    continue
                ts = int(c[1])
                bot.wipe_chat(ts)
                print()
                continue
            if c[0] == 'find':
                if len(c) != 2:
                    print('Username reauired')
                    continue
                bot.find_user(c[1])
                print()
                continue
            if c[0] == 'give':
                if len(c) < 2:
                    print('Usage: give (UID|random) [objects]\n')
                    continue
                bot.send_countries(c[1], list(map(str.upper, c[2:])), order)
                print()
                continue
            if c[0] == 'order':
                if len(c) == 1:
                    print(order, '\n')
                    continue
                if len(c) != 2 or c[1] not in ORDERS:
                    print('Available orders:', ', '.join(ORDERS), '\n')
                    continue
                order = c[1]
            if c[0] == 'list':
                for c in bot.list_countries(list(map(str.upper, c[1:])), order):
                    print(c.ljust(5), bot.map.country_names[c])
                print()
                continue
            if c[0] == 'defend':
                while True:
                    bot.adjust_items()
                    time.sleep(5)
            if len(c[0]) == 1 and c[0] in 'eca':
                bot.mode = c[0]
                c = c[1:]
            if c == ['*']:
                c = []
            c = list(map(str.upper, c))
            bot.update_map()
            bot.conquer(c, order)
            print()
        except KeyboardInterrupt:
            print('Interrupting')
            continue


if __name__ == '__main__':
    main()
