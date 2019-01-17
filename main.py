#!/usr/bin/env python3

import argparse
import json
import time
import random
import logging
import sys
import re
import traceback
import readline
import threading
from collections import defaultdict
from functools import partial

import requests

from socketIO_client import SocketIO

logging.getLogger('socketIO-client').setLevel(logging.ERROR)

CAPTCHA_WAIT_INTERVAL = 25
ROLL_INTERVAL = 1.05
USER_AGENT = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/53.0.2763.0 Safari/537.36'
HOST = 'https://worldroulette.ru/'
MAX_LEVEL = 3

WS_HOST = 'https://socket.worldroulette.ru'
WS_PORT = 444


def parse_args():
    parser = argparse.ArgumentParser(description='Bot for worldroulette.ru')
    parser.add_argument('sessions', nargs='*', help='session cookies from your browser')
    parser.add_argument('-c', '--captcha', action='store_true', help='always captcha warnings')
    return parser.parse_args()

ARGS = parse_args()


class SocketListener:

    def __init__(self, session):
        self.generation = 0
        self.session = session
        self.reconnect()

    def monitor(self, generation):
        sio = SocketIO(WS_HOST, WS_PORT, cookies={'session': self.session})
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
        if not data.startswith('jQuery.fn.vectorMap('):
            return
        data = data.replace('jQuery.fn.vectorMap(', '[').replace(');', ']').replace("'", '"')
        data = json.loads(data)[2]['paths']
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

    def sorted_list(self, order='random'):
        countries = list(self.world_state)
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
        return sorted(users, key=lambda x: (-x['countries'], -x['points'], int(x['id'])))

    def is_mine(self, region):
        return self.world_state[region][0] in self.me

    def get_level(self, region):
        return self.world_state[region][1]

    def get_owner_name(self, region):
        return self.players[self.world_state[region][0]]['name']

    def get_owner_id(self, region):
        return self.world_state[region][0]


class SessionManager:

    def __init__(self, sessions):
        self.sessions = sessions
        self._auth_attempts = 0
        self.auth()

    def auth(self):
        self._auth_attempts += 1
        if self._auth_attempts > 10:
            print('\nAuth failed')
            sys.exit(1)
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

    def adjust_items(self):
        data = json.loads(self.open_proc('inventory'))
        total = defaultdict(float)
        items = [{**data['items'][str(i)], 'aid': i} for i in data['inventory']['items']]
        items = sorted(items, key=lambda x: x['uses'], reverse=True)
        min_lifetime = 2000
        for item in items:
            item['stats'] = self.parse_stats(item['stats'])
            item['want'] = self.should_take(item['stats'], total)
            if item['want']:
                self.apply_stats(item['stats'], total)
                if 'luck' not in item['stats']:
                    min_lifetime = item['uses']
        for item in items:
            if not item['want'] or item['uses'] > min_lifetime or 'luck' in item['stats']:
                continue
            self.apply_stats(item['stats'], total, negate=True)
            if self.should_take(item['stats'], total):
                self.apply_stats(item['stats'], total)
            else:
                item['want'] = False
        for item in items:
            if item['want'] != bool(item['enabled']):
                self.open_proc('toggleItem', {'id': item['aid']})
                print(('Enabling' if item['want'] else 'Disabling'), item['name_ru'])

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

    @staticmethod
    def should_take(item_stats, total_stats):
        if item_stats.get('luck', 0) > 0 and total_stats['luck'] < 1.499:
            return True
        if item_stats.get('defence', 0) > 0 and total_stats['defence'] < 1.499:
            return True
        return False

class Roller:

    def __init__(self, open_proc, socket_listener):
        self.open_proc = open_proc
        self.last_roll = 0
        self.last_non_captcha = 0
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
            if (res['data'].startswith('ReCaptcha') and not ARGS.captcha and
                    time.time() < self.last_non_captcha + CAPTCHA_WAIT_INTERVAL):
                return ''
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
        return ''


def lookup_factions(ids, players, open_proc):
    factions = {i: players[i].get('fid') or None for i in ids if i in players}
    remaining = [i for i in ids if i not in players]
    if remaining:
        res = json.loads(open_proc('getplayers?ids=[' + ','.join(remaining) + ']'))
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

    def matches_one(self, country, item, online_list):
        if country.startswith(item.upper()) or self.map.country_names[country].upper().startswith(item.upper()):
            return True
        if item == self.map.get_owner_id(country) or self.map.get_owner_name(country).upper().startswith(item.upper()):
            return True
        if item.upper() == 'OFFLINE':
            if self.map.is_mine(country):
                return True
            owner = self.map.get_owner_id(country)
            if owner in online_list:
                return False
            if self.map.players[owner].get('fid') not in filter(bool, online_list.values()):
                return True
        return False

    def matches(self, country, object_list, online_list):
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
            if self.matches_one(country, item, online_list):
                if negate:
                    return False
                else:
                    matched = True
        if self.map.get_level(country) not in levels:
            return False
        return matched or not positive


class Bot:

    def __init__(self, sessions):
        self.conn = SessionManager(sessions)
        self.mode = 'a'
        self.map = Map(self.conn.ids)
        self.matcher = CountryMatcher(self.map)
        self.rollers = [Roller(partial(self.conn.open, opener=i), SocketListener(sessions[i])) for i in range(len(self.conn.ids))]
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
        while not self.map.is_mine(country):
            self.fight(country)
        self.send_to_batya(country)
        self.adjust_items()
        return True

    def empower_country(self, country):
        if not self.map.is_mine(country) or self.map.get_level(country) >= MAX_LEVEL:
            return False
        print('\nEmpowering {} ({}), level {}'.format(country, self.map.country_names[country],
                                                      self.map.get_level(country)))
        while self.map.get_level(country) < MAX_LEVEL:
            self.fight(country)
        print()
        self.adjust_items()
        return True


    def list_countries(self, object_list, order):
        tmap = self.map.sorted_list(order)
        online_list = self.get_online()
        online_with_factions = lookup_factions(online_list, self.map.players, partial(self.conn.open, opener=0))
        res = [name for name in tmap if self.matcher.matches(name, object_list, online_with_factions)]
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
                else:
                    res = self.open('give', {'target': c, 'targetplid': uid}, opener=0)
                time.sleep(1)
            print(res)
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


ORDERS = ['random', 'large', 'small']

def main():
    if ARGS.sessions:
        sessions = ARGS.sessions
        with open('accounts.txt', 'w') as f:
            f.write(' '.join(sessions))
    else:
        try:
            sessions = open('accounts.txt').read().split()
        except FileNotFoundError:
            print('accounts.txt does not exist')
            sys.exit()
    bot = Bot(sessions)
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
            c = input('Enter countries or users to conquer: ').split()
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
            for country in bot.map.sorted_list():
                bot.send_to_batya(country)
            bot.conquer(c, order)
            print()
        except KeyboardInterrupt:
            print('Interrupting')
            continue


if __name__ == '__main__':
    main()
