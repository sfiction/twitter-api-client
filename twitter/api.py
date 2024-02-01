
import json
import sys
from itertools import groupby

from .scraper import Scraper

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

def unwrap_tweet(obj):
    obj = obj['itemContent']
    # TODO: clientEventInfo
    assert obj['itemType'] == 'TimelineTweet', obj['itemType']
    assert obj['__typename'] == 'TimelineTweet', obj['__typename']
    assert obj['tweetDisplayType'] in ['Tweet', 'MediaGrid'], obj['tweetDisplayType']
    obj = obj['tweet_results']
    if not 'result' in obj: return None

    def build_user(obj):
        obj = obj['user_results']
        obj = obj['result']
        if obj['__typename'] == 'User':
            obj.pop('__typename')
        else:
            assert False, f'unknown result.__typename {obj["__typename"]}'
        id_str = obj['rest_id']
        obj = obj['legacy']

        t = {}
        t['id'] = int(id_str)
        t['id_str'] = id_str
        SELECT_KEYS = [
            'created_at',
            'description',
            'favourites_count',
            'followers_count',
            'friends_count',
            'listed_count',
            'media_count',
            'name',
            'screen_name',
            'statuses_count',
        ]
        for key in SELECT_KEYS:
            #if key in obj:
            t[key] = obj.pop(key)
        return t

    def build_tweet(obj):
        obj = obj['result']
        if obj['__typename'] == 'TweetWithVisibilityResults':
            obj = obj['tweet']
        elif obj['__typename'] == 'Tweet':
            obj.pop('__typename')
        else:
            assert False, f'unknown result.__typename {obj["__typename"]}'
        id_str = obj['rest_id']
        user = build_user(obj.pop('core'))
        obj = obj['legacy']
        obj.pop('extended_entities', None)

        t = {}
        t['id'] = int(id_str)
        t['id_str'] = id_str
        t['user'] = user
        if 'retweeted_status_result' in obj:
            t['retweeted_status'] = build_tweet(obj.pop('retweeted_status_result'))
        if 'quoted_status_result' in obj:
            t['quoted_status'] = build_tweet(obj.pop('quoted_status_result'))
        if 'entities' in obj:
            entities = obj.pop('entities')
            if 'media' in entities:
                t['media'] = entities.pop('media')
                for media in t['media']:
                    media.pop('features', None)
                    media.pop('sizes', None)
                    media.pop('indices', None)
                    media['original_info'].pop('focus_rects', None)
                    media['id'] = int(media['id_str'])
            if 'hashtags' in entities:
                t['hashtags'] = [tag['text'] for tag in entities['hashtags']]
            if 'urls' in entities:
                t['urls'] = [{key: url[key] for key in ['expanded_url', 'url']} for url in entities['urls']]
        t['text'] = obj.pop('full_text')

        SELECT_KEYS = [
            'bookmark_count',
            # 'bookmarked',
            'created_at',
            'favorite_count',
            # 'favorited',
            'lang',
            'possibly_sensitive',
            'quote_count',
            'reply_count',
            'retweet_count',
            # 'retweeted',
        ]
        for key in SELECT_KEYS:
            if key in obj:
                t[key] = obj.pop(key)
        assert t['id_str'] == obj.pop('id_str')
        assert t['user']['id_str'] == obj.pop('user_id_str')
        return t

    obj = build_tweet(obj)
    return obj

def unwrap_timeline_item(obj):
    entry_id = obj["entryId"]
    if entry_id.startswith('tweet-'):
        obj = obj['content']
        assert obj['entryType'] == 'TimelineTimelineItem', obj['entryType']
        assert obj['__typename'] == 'TimelineTimelineItem', obj['__typename']
        ret = [unwrap_tweet(obj)]
    elif entry_id.startswith('profile-conversation-'):
        obj = obj['content']
        assert obj['entryType'] == 'TimelineTimelineModule', obj['entryType']
        assert obj['__typename'] == 'TimelineTimelineModule', obj['__typename']
        items = obj['items']
        ret = []
        for obj in items:
            assert obj['entryId'].startswith('profile-conversation')
            obj = obj['item']
            ret.append(unwrap_tweet(obj))
    elif entry_id.startswith('profile-grid-'):
        obj = obj['content']
        assert obj['entryType'] == 'TimelineTimelineModule', obj['entryType']
        assert obj['__typename'] == 'TimelineTimelineModule', obj['__typename']
        items = obj['items']
        ret = []
        for obj in items:
            assert obj['entryId'].startswith('profile-grid-')
            obj = obj['item']
            ret.append(unwrap_tweet(obj))
    else:
        PREFIXES = [
            'promoted-tweet-',
            'who-to-follow-',
            'cursor-bottom-',
            'cursor-top-',
        ]
        if all(not entry_id.startswith(prefix) for prefix in PREFIXES):
            print(f'unknown entryId {entry_id}', file=sys.stderr)
            raise Exception(f'unknown entryId {entry_id}')
        ret = []
    ret = [obj for obj in ret if not obj is None]
    return ret

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

class Api(object):
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
            pin_entry = unwrap_timeline_item(pin_entry)[0]
        entries = sum(map(unwrap_timeline_item, entries), [])
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

    def get_user_tweets(self, *args, **kwargs):
        return self._get_user_timeline(self.scraper.tweets, *args, **kwargs)

    def get_user_media(self, *args, **kwargs):
        return self._get_user_timeline(self.scraper.media, *args, **kwargs)

    def get_user_timeline(self, *args, **kwargs):
        tweets = self.get_user_tweets(*args, **kwargs)
        media = self.get_user_media(*args, **kwargs)
        timeline = [list(gp)[0] for _, gp in groupby(sorted(tweets + media, key=get_id), key=get_id)]
        return timeline

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
