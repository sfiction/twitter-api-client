
import json
import sys
from itertools import groupby, chain
from typing import *

from .scraper import Scraper
from .transform import build_timeline_entry, build_tweet, build_user

def print_json(obj, **kwargs):
    kwargs = {'indent': 2, 'ensure_ascii': False, 'default': str} | kwargs
    print(json.dumps(obj, **kwargs))

def Get(obj, keys, strict=False):
    if strict:
        for key in keys.split('.'):
            obj = obj.get(key)
    else:
        for key in keys.split('.'):
            if key in obj:
                obj = obj[key]
            else:
                return None
    return obj

def get_cursor(entries):
    for entry in entries:
        entry_id = entry.get('entryId', '')
        if ('cursor-bottom' in entry_id) or ('cursor-showmorethreads' in entry_id):
            content = entry['content']
            if itemContent := content.get('itemContent'):
                return itemContent['value']  # v2 cursor
            return content['value']  # v1 cursor

def get_id(obj):
    return obj['id']

class Api:
    def __init__(self, req, debug=False):
        for line in req.split('\n'):
            if line.startswith('Cookie: '):
                cookie_value = line[8: ]
                break
        cookies = dict(pr.split('=', maxsplit=1) for pr in cookie_value.split('; '))
        self.scraper = Scraper(cookies=cookies, pbar=False, save=False, debug=debug)

    def _get_user_timeline_page(self, method, user_id, cursor=''):
        ret, cursor = method([int(user_id)], max_query=1, includePromotedContent=False, cursor=cursor)[0]
        ret = ret[0]
        if ret is None:
            return [], None, '-'
        insts = [inst for inst in Get(ret, 'data.user.result.timeline_v2.timeline.instructions', strict=True)
            if inst['type'] != 'TimelineClearCache']
        pin_entry = ([inst for inst in insts if inst['type'] == 'TimelinePinEntry'] or [{}])[0].get('entry', None)
        entries = ([inst for inst in insts if inst['type'] == 'TimelineAddEntries'] or [{}])[0].get('entries', [])
        cursor = get_cursor(entries)
        entries = [entry for entry in entries]
        if pin_entry:
            pin_entry = build_timeline_entry(pin_entry)[0]
        entries = sum(map(build_timeline_entry, entries), [])
        return entries, pin_entry, cursor

    def _get_user_timeline(self, method, user_id, *, since=None, until=None, count=None):
        user_id = int(user_id)
        if since is None: since = 0
        if until is None: until = 1 << 100
        if count is None: count = 1 << 60

        cursor = ''
        tweets = []
        while True:
            tweets_, pin, cursor = self._get_user_timeline_page(method, user_id, cursor=cursor)
            tweets.extend(tweets_)
            if not pin is None:
                tweets.append(pin)
            if len(tweets_) == 0: break
            if any(tweet['id'] <= since for tweet in tweets_): break
            if len(tweets) > count: break

        tweets = sorted((tweet for tweet in tweets if since < tweet['id'] <= until),
            key=get_id, reverse=True)
        tweets = [list(gp)[0] for _, gp in groupby(tweets, key=get_id)]
        return tweets

    def get_users(self, screen_names: list[str]=[], user_ids: list[int]=[]):
        users = []
        if screen_names:
            rets = self.scraper.users(screen_names)
            users.extend(build_user(Get(ret[0], 'data.user')) for ret in rets)
        if user_ids:
            if len(user_ids) <= 2:
                rets = self.scraper.users_by_id(user_ids)
                users.extend(build_user(Get(ret[0], 'data.user')) for ret in rets)
            else:
                rets = self.scraper.users_by_ids(user_ids)
                for ret in rets:
                    users.extend(build_user(user) for user in Get(ret[0], 'data.users'))
        return users

    def get_tweets(self, tweet_ids: list[Union[str, int]]):
        tweet_ids = list(map(int, tweet_ids))
        rets = self.scraper.tweets_by_id(tweet_ids)
        tweets = [build_tweet(Get(ret[0], 'data.tweetResult')) for ret in rets]
        return tweets

    def get_user_tweets(self, *args, **kwargs):
        return self._get_user_timeline(self.scraper.tweets, *args, **kwargs)

    def get_user_media(self, *args, **kwargs):
        return self._get_user_timeline(self.scraper.media, *args, **kwargs)

    def get_user_timeline(self, *args, **kwargs):
        tweets = self.get_user_tweets(*args, **kwargs)
        media = self.get_user_media(*args, **kwargs)
        timeline = [list(gp)[0] for _, gp in groupby(sorted(tweets + media, key=get_id), key=get_id)]
        return timeline

    def get_list(self, list_id: list[Union[str, int]], **kwargs):
        list_id = str(list_id)
        rets = self.scraper.list_members([list_id], **kwargs)[0]
        users = []
        for ret in rets:
            insts = Get(ret, 'data.list.members_timeline.timeline.instructions')
            entries = ([inst for inst in insts if inst['type'] == 'TimelineAddEntries'] or [{}])[0].get('entries', [])
            users.extend(chain.from_iterable(map(build_timeline_entry, entries)))
        return users

def main(req_file, screen_name, out=False, **kwargs):
    with open(req_file, encoding='utf-8', newline='\n') as fd:
        req = fd.read()
    api = Api(req, debug=True)

    user = api.scraper.users([screen_name])[0][0]['data']['user']['result']
    user_id = int(user['rest_id'])

    tweets = api.get_user_timeline(user_id, **kwargs)
    #tweets = api.get_user_media(user_id, **kwargs)
    #tweets = api.scraper.tweets([user_id], limit=count, includePromotedContent=False)
    #tweets = api.scraper.media([user_id], limit=count, includePromotedContent=False)
    if out:
        print_json(tweets, sort_keys=True)

if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    import fire
    fire.Fire(main)
