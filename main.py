#!/usr/bin/env python3

import signal
from engineio.client import original_signal_handler

signal.signal(signal.SIGINT, original_signal_handler)

try:
    import readline
except ImportError:
    pass

import argparse
import json
import time
import random
import sys
import math
import re
import os
from collections import defaultdict, namedtuple

import socketio
from Crypto.Cipher import AES
import struct


ROLL_INTERVAL = 1.1
USER_AGENT = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/53.0.2763.0 Safari/537.36'
HOST = 'https://worldroulette.ru/'
MAX_LEVEL = 3


def parse_args():
    parser = argparse.ArgumentParser(description='Bot for worldroulette.ru')
    parser.add_argument('sessions', nargs='*', help='session cookies from your browser')
    parser.add_argument('-i', '--no-items', action='store_true', help='disable item management')
    parser.add_argument('-g', '--guest', action='store_true', help='do not log in')
    parser.add_argument('-p', '--password', help='login:password')
    return parser.parse_args()

ARGS = parse_args()

Country = namedtuple('Country', ('name', 'area'))
CountryOwner = namedtuple('CountryOwner', ('user', 'power'))

with open('centroids.json', encoding='utf8') as f:
    CENTROIDS = json.load(f)
with open('neighbors.json', encoding='utf8') as f:
    NEIGHBORS = {k: set(v) for k, v in json.load(f).items()}
with open('map.json', encoding='utf8') as f:
    COUNTRIES = {k: Country(v['name'], v['area']) for k, v in json.load(f).items()}


def find_distance(bases, point):
    if not bases:
        return float('inf')
    return min((i[0] - point[0]) ** 2 + (i[1] - point[1]) ** 2 for i in bases)


class CredentialsManager:

    def __init__(self):
        with open('accounts.txt', encoding='utf8') as f:
            self.fingerprint, self.session = f.read().split()

    def update_session(self, session):
        self.session = session
        with open('accounts.txt', 'w', encoding='utf8') as f:
            f.write(self.fingerprint + ' ' + session)

credentials = CredentialsManager()


class Store:

    def __init__(self):
        self.me = None
        self.users = {}
        self.countries = {}
        self.clans = {}
        self.online = set()

    def update_users(self, users):
        for u in users:
            self.users[u['id']] = u

    def update_countries(self, countries):
        for c in countries:
            self.countries[c['code']] = CountryOwner(c['owner'], c['power'])

    def update_clans(self, clans):
        for c in clans:
            self.clans[c['id']] = c['name']

    def update_online(self, online):
        self.online = {int(u['user']) for u in online}

    def add_online(self, online):
        self.online.add(int(online['user']))

    def remove_online(self, online):
        self.online.discard(int(online))

    def is_mine(self, country, allow_mates=True):
        if self.countries[country][0] == self.me:
            return True
        if not allow_mates:
            return False
        if (self.users[self.me]['clan'] is not None and
                self.users[self.me]['clan'] == self.users[self.countries[country].user]['clan']):
            return True
        return False

    def is_online(self, user, include_clan=True):
        if user in self.online:
            return True
        if include_clan and self.users[user]['clan']:
            clan = self.users[user]['clan']
            return any(self.users[u]['clan'] == clan for u in self.online)
        return False

    def get_owner_id(self, country):
        return self.countries[country].user

    def get_power(self, country):
        return self.countries[country].power

    def get_owner_name(self, country):
        return self.users[self.countries[country].user]['name']

    def get_clan_id(self, user):
        return self.users[user]['clan']

    def get_clan_name(self, user):
        clan = self.users[user]['clan']
        return None if clan is None else self.clans[clan]

    def get_user_representation(self, user):
        name = self.users[user]['name']
        clan = self.users[user]['clan']
        if user in self.online:
            name = '*' + name
        if clan is None:
            return name
        else:
            clan = self.clans[clan]
            if self.is_online(user):
                clan = '*' + clan
            return '{} [{}]'.format(name, clan)

store = Store()


def _points_to_win(country):
    if store.is_mine(country):
        return store.countries[country][1] - 100
    return store.countries[country][1]


def sorted_countries(order):
    countries = list(store.countries)
    if order == 'near' or order == 'conn':
        mine = {c for c in countries if store.is_mine(c, False)}
        not_mine = [c for c in countries if not store.is_mine(c, False)]
        random.shuffle(not_mine)
        dists = sorted(((find_distance([CENTROIDS[i] for i in NEIGHBORS[c].intersection(mine)], CENTROIDS[c]), c) for c in not_mine),
                        key=lambda x: x[0])
        if order == 'conn':
            dists = [i for i in dists if math.isfinite(i[0])]
        return sorted(mine, key=_points_to_win) + [i[1] for i in dists]
    if order == 'random':
        random.shuffle(countries)
        countries.sort(key=_points_to_win)
    elif order == 'small':
        countries.sort(key=lambda x: COUNTRIES[x].area)
    elif order == 'large':
        countries.sort(key=lambda x: COUNTRIES[x].area, reverse=True)
    return countries


def get_player_list():
    countries = defaultdict(int)
    points = defaultdict(int)
    for value in store.countries.values():
        countries[value.user] += 1
        points[value.user] += value.power
    users = [{'id': i, 'name': store.get_user_representation(i), 'countries': countries[i], 'points': points[i]}
                for i in store.users if points[i]]
    return sorted(users, key=lambda x: (-x['points'], -x['countries'], int(x['id'])))


def putchar(c):
    print(c, end='', flush=True)


ROLL_RESULT_RE = re.compile(r'^Вам выпало (\d\d\d\d)')
class SessionManager:

    def __init__(self, loginpass=None):
        self.client = socketio.Client()
        self.client.connect(HOST)
        self.client.on('setUser', self.set_user_id)
        self.client.on('updateMap', self.update_map)
        self.client.on('updateOnline', self.update_online)
        self.client.on('notification', self.notification)
        aes = AES.new(b'woro' * 8, AES.MODE_CTR, nonce=b'', initial_value=self.client.sid.encode()[:16])
        self.encrypted_fingerprint = aes.encrypt(credentials.fingerprint.encode())
        self.get_auth(not ARGS.guest and not ARGS.password)
        if loginpass:
            login, password = loginpass.split(':', maxsplit=1)
            self.client.on('setSession', self.set_session)
            self.client.emit('sendAuth', ({'login': login, 'password': password, 'shouldCreate': False}, self.encrypted_fingerprint))
            while store.me is not None:
                time.sleep(0.1)
            self.get_auth(True)
        if not ARGS.guest and store.me == 10:
            print('Auth failure')
            sys.exit(1)

    def get_auth(self, add_session):
        store.me = None
        self.client.emit('getAuth', (credentials.session if add_session else None, self.encrypted_fingerprint))
        while store.me is None:
            time.sleep(0.1)

    def set_session(self, session):
        credentials.update_session(session)
        store.me = None

    def set_user_id(self, msg):
        store.me = msg

    def update_map(self, msg):
        store.update_clans(msg.get('clans', []))
        store.update_users(msg.get('users', []))
        store.update_countries(msg.get('lands', []))

    def update_online(self, msg):
        store.update_clans(msg.get('clans', []))
        store.update_users(msg.get('users', []))
        if 'online' in msg:
            store.update_online(msg['online'])
        if 'changeOnline' in msg:
            store.add_online(msg['changeOnline'])
        if 'removeOnline' in msg:
            store.remove_online(msg['removeOnline'])

    def notification(self, result, msg, *args):
        if msg == 'Неверный пароль!':
            print(msg)
        match = ROLL_RESULT_RE.match(msg)
        if match:
            num = match.group(1)
            if num[3] != num[2]:
                putchar('.')
            elif num[2] != num[1]:
                putchar('*')
            elif num[1] != num[0]:
                putchar('#')
            else:
                putchar('@')

    def emit(self, command, *params):
        self.client.emit(command, tuple(params))

    def close(self):
        self.client.disconnect()


class Roller:

    def __init__(self, session):
        self.session = session
        self.last_roll = 0

    def roll(self, target):
        now = time.time()
        if now < self.last_roll + ROLL_INTERVAL:
            time.sleep(self.last_roll + ROLL_INTERVAL - now)
        self.last_roll = time.time()
        self.session.emit('roll', target)
        time.sleep(0.3)


class MatchingError(Exception):
    pass


def consume_negation(item):
    if item.startswith('-'):
        return True, item[1:]
    if item.startswith('+'):
        return False, item[1:]
    return None, item


def matches_one(country, item, cache):
    if item == '@':
        item = str(store.me)
    if item.startswith('$'):
        if item[1:] not in cache['aliases']:
            if not is_alias_name(item[1:]):
                raise MatchingError('Invalid alias name: ' + item)
            countries = load_countries(item[1:])
            if countries is None:
                raise MatchingError('No such alias: ' + item)
            cache['aliases'][item[1:]] = set(countries)
        return country in cache['aliases'][item[1:]]
    if country.startswith(item.upper()) or COUNTRIES[country].name.upper().startswith(item):
        return True
    owner = store.get_owner_id(country)
    if item == str(owner) or store.get_owner_name(country).upper().startswith(item):
        if item.upper() not in COUNTRIES:
            return True
    if item == 'C' + str(store.get_clan_id(owner)) or (store.get_clan_name(owner) or '').upper().startswith(item):
        return True
    if item in ['OFFLINE', 'ONLINE']:
        if owner not in cache['online']:
            cache['online'][owner] = store.is_online(owner)
        if cache['online'][owner] == (item == 'ONLINE'):
            return True

    return False


def consume(object_list):
    for item in object_list:
        if item == ')':
            return


def matches(country, object_list, cache):
    object_list = iter(object_list)
    matched = False
    positive = False
    levels = list(range(1, MAX_LEVEL + 1))
    for item in object_list:
        if item == ')':
            break
        if item.startswith('^'):
            if item[1:].isdigit():
                levels = list(map(int, item[1:]))
            continue
        negate, item = consume_negation(item)
        if negate is None:
            positive = True
        if item == '(':
            success = matches(country, object_list, cache)
        else:
            success = matches_one(country, item, cache)
        if success:
            if negate:
                consume(object_list)
                return False
            elif negate is None:
                matched = True
        elif negate is False:
            consume(object_list)
            return False
    if store.get_power(country) not in levels:
        return False
    return matched or not positive


class Bot:

    def __init__(self, session):
        self.session = session
        self.mode = 'a'
        self.roller = Roller(self.session)

    def conquer_country(self, country):
        if store.is_mine(country):
            return False
        print('\nConquering {} ({}), level {}, belongs to {}'.format(country, COUNTRIES[country].name,
                                                                     store.get_power(country),
                                                                     store.get_user_representation(store.get_owner_id(country))))
        rolls = 0
        while not store.is_mine(country):
            self.roller.roll(country)
            rolls += 1
            if rolls > 40:
                print('Too tired')
                return True
        return True

    def empower_country(self, country):
        if not store.is_mine(country) or store.get_power(country) >= MAX_LEVEL:
            return False
        print('\nEmpowering {} ({}), level {}'.format(country, COUNTRIES[country].name,
                                                      store.get_power(country)))
        rolls = 0
        while store.is_mine(country) and store.get_power(country) < MAX_LEVEL:
            self.roller.roll(country)
            rolls += 1
            if rolls > 40:
                print('Too tired')
                return True
        print()
        return True


    def list_countries(self, object_list, order):
        tmap = sorted_countries(order)
        cache = defaultdict(dict)
        res = [name for name in tmap if matches(name, object_list, cache)]
        return res


    def conquer(self, object_list, order, mode):
        while True:
            changed = 0
            for name in self.list_countries(object_list, order):
                if mode == 'e':
                    changed += self.empower_country(name)
                elif mode == 'c':
                    changed += self.conquer_country(name)
                elif mode == 'a':
                    changed += self.conquer_country(name)
                    changed += self.empower_country(name)
                if changed:
                    break
            else:
                return
            if not changed:
                return


ALIASES_DIR = 'aliases'


def is_alias_name(name):
    return name.replace('_', '').replace('-', '').isalnum()

def save_countries(countries, name):
    if not os.path.isdir(ALIASES_DIR):
        os.mkdir(ALIASES_DIR)
    with open(os.path.join(ALIASES_DIR, name), 'w', encoding='utf8') as f:
        f.write(' '.join(countries))


def load_countries(name):
    try:
        with open(os.path.join(ALIASES_DIR, name), encoding='utf8') as f:
            return f.read().split()
    except FileNotFoundError:
        return None


def list_aliases():
    for name in os.listdir(ALIASES_DIR):
        if os.path.isfile(os.path.join(ALIASES_DIR, name)) and is_alias_name(name):
            print(name.lower())


def print_country_list(countries):
    if not countries:
        print('Nothing to list')
        return
    max_name = max(len(COUNTRIES[c].name) for c in countries)
    for c in countries:
        print('{} {}  {}'.format(c.ljust(5), COUNTRIES[c].name.ljust(max_name), store.get_user_representation(store.get_owner_id(c))))


def compare_lists(lhs, rhs):
    lhs = set(lhs)
    rhs = set(rhs)
    plus = {c for c in rhs if c not in lhs}
    minus = {c for c in lhs if c not in rhs}
    print('Left:')
    print_country_list(minus)
    print()
    print('Right:')
    print_country_list(plus)
    print()


ORDERS = ['near', 'conn', 'random', 'large', 'small']
MODES = ['a', 'c', 'e']

def main():
    if ARGS.sessions:
        credentials.update_session(ARGS.sessions[0])
    bot = Bot(SessionManager(ARGS.password or None))
    order = ORDERS[0]
    mode = MODES[0]
    try:
        while True:
            print('Users on the map:\n' + '\n'.join('[{id:4}] {name} ({countries}, {points})'.format(**i)
                                                    for i in get_player_list()))
            print()
            try:
                c = input('({} {})> '.format(order, mode)).split()
            except EOFError:
                print()
                return
            if not c:
                continue
            try:
                if c[0] == 'exit':
                    break
                if c[0].startswith('!'):
                    val = c[0][1:]
                    if val == '!':
                        order = ORDERS[0]
                        mode = MODES[0]
                    elif val in ORDERS:
                        order = val
                    elif val in MODES:
                        mode = val
                    else:
                        print('Available orders:', ', '.join(ORDERS))
                        print('Available modes:', ', '.join(MODES))
                        print()
                    continue
                if c[0] == 'list':
                    print_country_list(bot.list_countries(list(map(str.upper, c[1:])), order))
                    print()
                    continue
                if c[0] == 'clans':
                    for c, name in sorted(store.clans.items()):
                        print(str(c).ljust(4), name)
                    print()
                    continue
                if c[0] == 'alias':
                    if len(c) < 2:
                        list_aliases()
                        print()
                        continue
                    if not is_alias_name(c[1]):
                        print('Invalid alias name')
                        print()
                        continue
                    countries = sorted(bot.list_countries(list(map(str.upper, c[2:])), None))
                    save_countries(countries, c[1].upper())
                    print('Saved')
                    print()
                    continue
                loop = False
                if c[0] == 'loop':
                    loop = True
                    c = c[1:]
                if c == ['*']:
                    c = []
                c = list(map(str.upper, c))
                if c.count('<>') == 1:
                    lhs = bot.list_countries(c[:c.index('<>')], None)
                    rhs = bot.list_countries(c[c.index('<>') + 1:], None)
                    compare_lists(lhs, rhs)
                    continue
                while True:
                    bot.conquer(c, order, mode)
                    if not loop:
                        break
                    time.sleep(1)
                print()
            except MatchingError as e:
                print(e.args[0])
                print()
                continue
            except KeyboardInterrupt:
                print('Interrupting')
                continue
    finally:
        bot.session.close()


if __name__ == '__main__':
    main()
