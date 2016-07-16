#!/usr/bin/python3

import urllib.request
import urllib.parse
from http.cookiejar import CookieJar
import re
import json
import time
import sys

class CaptchaNeeded(Exception):
    pass

class Bot:
    host = 'http://worldroulette.ru/'

    def __init__(self, login, password):
        self.login = login.lower()
        cj = CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
        self.opener.addheaders = [('User-Agent', 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/53.0.2763.0 Safari/537.36')]
        pg = self.open('')
        opts = dict(re.findall(r'<input type="hidden" name="([^"]+)" value="([^"]+)" />', pg))
        opts['Submit'] = ''
        opts['username'] = login
        opts['password'] = password
        self.open('', opts)
        self.getMapInfo()

    def open(self, uri, params=None):
        try:
            if params is None:
                return self.opener.open(self.host + uri).read().decode('utf-8')
            else:
                return self.opener.open(self.host + uri, urllib.parse.urlencode(params).encode('utf-8')).read().decode('utf-8')
        except Exception:
            return ''

    def getMapInfo(self):
        pg = self.open('getUser.php').replace('\n', ' ').strip()
        fractions, users, levels = [json.loads(i) for i in re.findall(r'({.+})S1G2@gaAVd({.+})Gk2kF91k@4({.+})', pg)[0]]
        self.user_to_frac = {}
        for i in fractions:
            frac = '<none>'
            if fractions[i]:
                frac = fractions[i].split(':', maxsplit=1)[1].strip()
            self.user_to_frac[users[i]] = frac
        self.map = {i:(users[i],levels[i],fractions[i]) for i in users}

    def fight(self, country, silent=False):
        res = self.open('post.php', {'Country': country, 'grecaptcharesponse': ''})
        time.sleep(6)
        if 'Вы не ввели капчу' in res:
            if not silent:
                print('[CAPTCHA]', end='')
                sys.stdout.flush()
            return self.fight(country, True)
        print(('*' if 'она была ухудшена' in res else '.'), end='')
        sys.stdout.flush()
        ans = 'Теперь территория принадлежит' in res or 'ваша территория' in res or 'Теперь она принадлежит' in res
        if ans:
            print(country, 'conquered')
        return ans

    def conquer(self, object_list):
        self.getMapInfo()
        tmap = sorted(self.map, key=lambda x:(self.map[x][1], x))
        while True:
            for name in tmap:
                if name.lower() in object_list or self.map[name][0].lower() in object_list:
                    if self.map[name][0].lower() == self.login:
                        continue
                    self.conquerCountry(name)
                    self.getMapInfo()
                    tmap = sorted(self.map, key=lambda x:(self.map[x][1], x))
                    break
            else:
                break

    def conquerCountry(self, country):
        if self.map[country][0].lower() == self.login:
            return
        print('Conquering {} ({}), level {}, belongs to {}'.format(country, countries[country], self.map[country][1], self.map[country][0]))
        while not self.fight(country):
            pass

    def punishUser(self, user):
        user = user.lower()
        self.getMapInfo()
        for i in sorted(self.map, key=lambda x:(self.map[x][1], x)):
            if (user == '*' and self.map[i][0].lower() != login) or self.map[i][0].lower() == user:
                self.conquerCountry(i)

    def giveAll(self, user):
        self.open('give.php', {'All': 'true', 'auid': user})


countries = dict(i.strip().split(maxsplit=1) for i in open('countries.txt', encoding='utf-8') if i)

def main():
    lp = [i.split() for i in open('accounts.txt') if i.strip() and i[0] != '#']
    mainbot = Bot(lp[0][0], lp[0][1])
    users = {i[0] for i in mainbot.map.values()}
    users = [(i, sum(mainbot.map[j][0] == i for j in mainbot.map), mainbot.user_to_frac[i]) for i in users]
    print('Users on the map:' , ', '.join('{0}:{2} ({1})'.format(*i) for i in sorted(users, key=lambda x:-x[1])))
    c = input('Enter countries or users to conquer: ').lower().split()
    mainbot.conquer(c)


if __name__ == '__main__':
    main()

