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

    def open(self, uri, params=None):
        if params is None:
            return self.opener.open(self.host + uri).read().decode('utf-8')
        else:
            return self.opener.open(self.host + uri, urllib.parse.urlencode(params).encode('utf-8')).read().decode('utf-8')

    def getMapInfo(self):
        pg = self.open('getUser.php').replace('\n', ' ').strip()
        fractions, users, levels = [json.loads(i) for i in re.findall(r'({.+})S1G2@gaAVd({.+})Gk2kF91k@4({.+})', pg)[0]]
        self.map = {i:(users[i],levels[i]) for i in users}

    def fight(self, country):
        res = self.open('post.php', {'Country': country, 'grecaptcharesponse': ''})
        time.sleep(6)
        print(('*' if 'она была ухудшена' in res else '.'), end='')
        sys.stdout.flush()
        if res.startswith('docaptcha'):
            raise CaptchaNeeded
        return 'Теперь территория принадлежит' in res or 'ваша территория' in res

    def conquerCountry(self, country):
        self.getMapInfo()
        if self.map[country][0] in logins:
            return
        print('Conquering {}, level {}'.format(country, self.map[country][1]))
        while not self.fight(country):
            pass
        print(country, 'conquered')

    def punishUser(self, user):
        user = user.lower()
        self.getMapInfo()
        for i in sorted(self.map, key=lambda x:(self.map[x][1], x)):
            if self.map[i][0].lower() == user:
                self.conquerCountry(i)

    def giveAll(self, user):
        self.open('give.php', {'All': 'true', 'auid': user})


logins = {}

def main():
    lp = [i.split() for i in open('accounts.txt') if i.strip()]
    bots = [Bot(login, password) for login, password in lp]
    global logins
    logins = {i[0] for i in lp}
    bots[0].getMapInfo()
    print('Users on the map:' , ', '.join({i[0] for i in bots[0].map.values()}))
    c = input('Enter countries or users to conquer: ').upper().split()
    for b in bots:
        print('Using account', b.login)
        try:
            for i in c:
                if len(i) == 2:
                    b.conquerCountry(i.upper())
                else:
                    b.punishUser(i)
            break
        except CaptchaNeeded:
            print('Captcha needed for', b.login)
            pass
    for b in bots[1:]:
        b.giveAll(lp[0][0])
        print('Sending everything from {} to {}'.format(b.login, lp[0][0]))


if __name__ == '__main__':
    main()

