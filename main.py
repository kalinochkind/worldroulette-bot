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
import threading
from collections import defaultdict, namedtuple

import socketio
from Crypto.Cipher import AES
import struct
import requests


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
    parser.add_argument('-s', '--server', default='0')
    return parser.parse_args()

ARGS = parse_args()

Country = namedtuple('Country', ('name', 'area'))
CountryOwner = namedtuple('CountryOwner', ('user', 'power'))

with open('neighbors.json', encoding='utf8') as f:
    NEIGHBORS = {k: set(v) for k, v in json.load(f).items()}
with open('map.json', encoding='utf8') as f:
    COUNTRIES = {k: Country(v['name'], float(v['area'])) for k, v in json.load(f).items()}


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
        self.me = self._me = None
        self.users = {}
        self.countries = {}
        self.clans = {}
        self.items = {}
        self.base_items = {}
        self.online = set()
        self.captcha = None

    def reset(self):
        self.countries = {}
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

    def update_captcha(self, captcha):
        self.captcha = captcha

    def update_items(self, base_items, items):
        for bi in base_items:
            self.base_items[bi['id']] = bi['name']
        for it in items:
            if it['owner'] == self.me:
                if not it['deleted']:
                    if it['baseItem'] in self.base_items:
                        self.items[it['id']] = self.base_items[it['baseItem']]
                elif it['id'] in self.items:
                    del self.items[it['id']]

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

    def get_energy(self):
        return self.users[self.me]['energy']

store = Store()


def sorted_countries(order):
    mine = [c for c in store.countries if store.is_mine(c, False)]
    not_mine = [c for c in store.countries if not store.is_mine(c, False)]
    if order == 'near' or order == 'conn':
        random.shuffle(not_mine)
        mine_set = set(mine)
        dists = sorted(((-sum(n in mine for n in NEIGHBORS[c]), c) for c in not_mine), key=lambda x: x[0])
        if order == 'conn':
            dists = [i for i in dists if i[0] < 0]
        return sorted(mine, key=store.get_power), [i[1] for i in dists]
    if order == 'random':
        random.shuffle(mine)
        random.shuffle(not_mine)
        return sorted(mine, key=store.get_power), sorted(not_mine, key=store.get_power)
    elif order == 'small':
        return sorted(mine, key=lambda x: COUNTRIES[x].area), sorted(not_mine, key=lambda x: COUNTRIES[x].area)
    elif order == 'large':
        return sorted(mine, key=lambda x: -COUNTRIES[x].area), sorted(not_mine, key=lambda x: -COUNTRIES[x].area)
    return mine, not_mine


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

    def __init__(self, loginpass=None, namespace=''):
        self.namespace = '/' + namespace
        self.lock = threading.Lock()
        with self.lock:
            self.connect(loginpass)

    def connect(self, loginpass=None):
        self.client = socketio.Client()
        self.client.on('setUser', self.set_user_id, namespace=self.namespace)
        self.client.on('updateMap', self.update_map, namespace=self.namespace)
        self.client.on('updateOnline', self.update_online, namespace=self.namespace)
        self.client.on('notification', self.notification, namespace=self.namespace)
        self.client.on('getCaptcha', self.get_captcha, namespace=self.namespace)
        self.client.on('wrongCaptcha', self.wrong_captcha, namespace=self.namespace)
        self.client.connect(HOST, namespaces=[self.namespace])
        aes = AES.new(b'woro' * 8, AES.MODE_CTR, nonce=b'', initial_value=(self.namespace + '#' + self.client.sid).encode()[:16])
        self.encrypted_fingerprint = aes.encrypt(credentials.fingerprint.encode())
        self.get_auth(not ARGS.guest and not loginpass)
        if loginpass:
            login, password = loginpass.split(':', maxsplit=1)
            self.client.on('setSession', self.set_session, namespace=self.namespace)
            self.client.emit('sendAuth', ({'login': login, 'password': password, 'shouldCreate': False}, self.encrypted_fingerprint), namespace=self.namespace)
            while store._me is not None:
                time.sleep(0.1)
            self.client.disconnect()
            time.sleep(0.3)
            return self.connect()
        if not ARGS.guest and store._me == 10:
            print('Auth failure')
            sys.exit(1)
        self.client.emit('getCaptcha', namespace=self.namespace)

    def get_auth(self, add_session):
        store._me = None
        self.client.emit('getAuth', (credentials.session if add_session else None, self.encrypted_fingerprint), namespace=self.namespace)
        while store._me is None:
            time.sleep(0.1)

    def set_session(self, session):
        credentials.update_session(session)
        store._me = None

    def set_user_id(self, msg):
        store.me = msg
        store._me = msg

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
        if 'items' in msg:
            store.update_items(msg.get('baseItems', []), msg['items'])

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

    def get_captcha(self, data=None):
        if data:
            store.update_captcha(data['svg'])

    def wrong_captcha(self):
        with self.lock:
            self.close()
            self.connect()

    def emit(self, command, *params):
        with self.lock:
            self.client.emit(command, tuple(params), namespace=self.namespace)

    def close(self):
        self.client.disconnect()

    def change_namespace(self, namespace):
        with self.lock:
            self.close()
            self.namespace = '/' + namespace
            self.connect()


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
    elif item == '@@':
        item = 'C' + str(store.get_clan_id(store.me))
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
            cache['online'][owner] = store.is_online(owner, False)
        if cache['online'][owner] == (item == 'ONLINE'):
            return True
    if item in ['CLANOFFLINE', 'CLANONLINE']:
        if owner not in cache['clanonline']:
            cache['clanonline'][owner] = store.is_online(owner)
        if cache['clanonline'][owner] == (item == 'CLANONLINE'):
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
        self.tokens = -1
        self.roller = Roller(self.session)
        self.watcher = threading.Thread(target=self.captcha_watcher, daemon=True)
        self.watcher.start()

    def conquer_country(self, country, limit):
        if store.is_mine(country) or (limit < 0 and store.get_power(country) <= -limit):
            return False
        print('\nConquering {} ({}), level {}, belongs to {}'.format(country, COUNTRIES[country].name,
                                                                     store.get_power(country),
                                                                     store.get_user_representation(store.get_owner_id(country))))
        rolls = 0
        while not store.is_mine(country) and (limit > 0 or store.get_power(country) > -limit):
            self.roller.roll(country)
            rolls += 1
            if rolls > 50:
                print('Too tired')
                return True
        print()
        return True

    def empower_country(self, country, limit):
        if not store.is_mine(country) or store.get_power(country) >= limit:
            return False
        print('\nEmpowering {} ({}), level {}{}'.format(country, COUNTRIES[country].name,
            store.get_power(country),
            '' if store.is_mine(country, False) else ', belongs to ' + store.get_user_representation(store.get_owner_id(country))))
        rolls = 0
        while store.is_mine(country) and store.get_power(country) < limit:
            self.roller.roll(country)
            rolls += 1
            if rolls > 50:
                print('Too tired')
                return True
        print()
        return True


    def list_countries(self, object_list, order=None, mode=None):
        mine, not_mine = sorted_countries(order)
        if mode == 'a':
            tmap = not_mine + mine
        else:
            tmap = mine + not_mine
        cache = defaultdict(dict)
        res = [name for name in tmap if matches(name, object_list, cache)]
        return res


    def conquer(self, object_list, order, mode, limit):
        while True:
            changed = 0
            for name in self.list_countries(object_list, order, mode):
                if self.tokens == 0:
                    print('No tokens left')
                    return
                changed += self.conquer_country(name, limit)
                changed += self.empower_country(name, limit)
                if changed:
                    if self.tokens > 0:
                        self.tokens -= 1
                    break
            else:
                return
            if not changed:
                return

    def captcha_watcher(self):
        while True:
            try:
                if store.get_energy() <= 15 and store.captcha:
                    captcha = store.captcha
                    res = requests.post('https://bladdon.ru/solvecaptcha', data=captcha).text
                    self.session.emit('checkCaptcha', res)
                    store.captcha = None
                time.sleep(0.5)
            except Exception:
                print('Captcha failed')
                time.sleep(3)

    def sell_all(self):
        for id, name in list(store.items.items()):
            if name == 'Кейс':
                continue
            self.session.emit('sellItem', id)
            print('Selling', name)
            time.sleep(0.3)

    def open_case(self):
        for id, name in list(store.items.items()):
            if name == 'Кейс':
                self.session.emit('openItem', id)
                print('Opening')


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
MODES = ['d', 'a']


def main():
    if ARGS.sessions:
        credentials.update_session(ARGS.sessions[0])
    bot = Bot(SessionManager(ARGS.password or None, namespace=ARGS.server))
    order = ORDERS[0]
    mode = MODES[0]
    max_level = MAX_LEVEL
    try:
        while True:
            print('Users on the map:\n' + '\n'.join('[{id:4}] {name} ({countries}, {points})'.format(**i)
                                                    for i in get_player_list()))
            print()
            try:
                c = input('{} ({} {}{})> '.format(bot.session.namespace, order, mode, max_level)).split()
            except EOFError:
                print()
                return
            if not c:
                continue
            try:
                if c[0] == 'exit':
                    break
                if c[0].startswith('/'):
                    num = c[0][1:]
                    if num in ['0', '1', '2', '3', '']:
                        store.reset()
                        bot.session.change_namespace(num or bot.session.namespace[1:])
                        print()
                        continue
                    print('Wrong server')
                    continue
                if c[0].startswith('!'):
                    val = c[0][1:]
                    if val == '!':
                        order = ORDERS[0]
                        mode = MODES[0]
                        max_level = MAX_LEVEL
                    elif val in ORDERS:
                        order = val
                    elif val in MODES:
                        mode = val
                    elif val in {str(i) for i in range(-MAX_LEVEL + 1, MAX_LEVEL + 1) if i}:
                        max_level = int(val)
                    else:
                        print('Available orders:', ', '.join(ORDERS))
                        print('Available modes:', ', '.join(MODES))
                        print()
                    continue
                if c[0] == 'sellall':
                    bot.sell_all()
                    print()
                    continue
                if c[0] == 'mine':
                    while True:
                        bot.open_case()
                        bot.sell_all()
                        time.sleep(0.5)
                if c[0] == 'list':
                    print_country_list(bot.list_countries(list(map(str.upper, c[1:])), order, mode))
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
                    countries = sorted(bot.list_countries(list(map(str.upper, c[2:]))))
                    save_countries(countries, c[1].upper())
                    print('Saved')
                    print()
                    continue
                if c[0] == 'tokens':
                    if len(c) == 1:
                        print(bot.tokens)
                        print()
                        continue
                    try:
                        tokens = int(c[1])
                    except ValueError:
                        print('Bad number of tokens')
                        print()
                        continue
                    bot.tokens = tokens
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
                    lhs = bot.list_countries(c[:c.index('<>')])
                    rhs = bot.list_countries(c[c.index('<>') + 1:])
                    compare_lists(lhs, rhs)
                    continue
                while True:
                    bot.conquer(c, order, mode, max_level)
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
