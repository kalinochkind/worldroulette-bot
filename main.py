#!/usr/bin/python3

import urllib.request
import urllib.parse
from http.cookiejar import CookieJar
import re
import json
import time
import sys
import threading
import queue
ROLL_INTERVAL = 5


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
        time.sleep(ROLL_INTERVAL)
        if 'Вы не ввели капчу' in res:
            if not silent:
                print('CAPTCHA FOR', self.login)
                sys.stdout.flush()
            return self.fight(country, True)
        sys.stdout.flush()
        ans = 'Теперь территория принадлежит' in res or 'ваша территория' in res or 'Теперь она принадлежит' in res
        if ans:
            print(self.login + ':', country, 'conquered')
        return ans

    def conquerCountry(self, country):
        if self.map[country][0].lower() == self.login:
            return
        print('{}: conquering {} ({}), level {}, belongs to {}'.format(self.login, country, countries[country], self.map[country][1], self.map[country][0]))
        while not self.fight(country):
            pass

    def giveAll(self, user):
        if self.login != user:
            self.open('give.php', {'All': 'true', 'auid': user})

class BotManager:
    def __init__(self, lp):
        self.bots = [Bot(l, p) for l, p in lp]
        self.bots[0].getMapInfo()
        self.logins = [i[0].lower() for i in lp]
        self.queue = queue.Queue(1)

    def sorted_map(self):
        return sorted(self.bots[0].map, key=lambda x:(self.bots[0].map[x][1], x))

    def conquer(self, object_list):
        threads = [threading.Thread(target=lambda i=i:self.work(i, self.bots[0].login)) for i in self.bots]
        for i in threads:
            i.start()
        self.bots[0].getMapInfo()
        tmap = self.sorted_map()
        for name in tmap:
            if name.lower() in object_list or self.bots[0].map[name][0].lower() in object_list or '*' in object_list:
                if self.bots[0].map[name][0].lower() in self.logins:
                    continue
                self.queue.put(name)
                self.bots[0].getMapInfo()
        for i in self.bots:
            self.queue.put(None)

    def work(self, bot, sendto):
        while True:
            name = self.queue.get()
            if name is None:
                bot.giveAll(sendto)
                return
            bot.getMapInfo()
            bot.conquerCountry(name)

countries = dict(i.strip().split(maxsplit=1) for i in open('countries.txt', encoding='utf-8') if i)

def main():
    lp = [i.split() for i in open('accounts.txt') if i.strip() and i[0] != '#']
    logins = {i[0].lower() for i in lp}
    bm = BotManager(lp)
    mainbot = bm.bots[0]
    users = {i[0] for i in mainbot.map.values()}
    users = [(i, sum(mainbot.map[j][0] == i for j in mainbot.map), mainbot.user_to_frac[i]) for i in users]
    print('Users on the map:' , ', '.join('{0}:{2} ({1})'.format(*i) for i in sorted(users, key=lambda x:-x[1])))
    c = input('Enter countries or users to conquer: ').lower().split()
    bm.conquer(c)


if __name__ == '__main__':
    main()

