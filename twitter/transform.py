
import sys

def build_user(obj):
    if not 'result' in obj: return None
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
    if not 'result' in obj: return None
    obj = obj['result']
    if obj['__typename'] == 'TweetWithVisibilityResults':
        obj = obj['tweet']
    elif obj['__typename'] == 'Tweet':
        obj.pop('__typename')
    else:
        assert False, f'unknown result.__typename {obj["__typename"]}'
    id_str = obj['rest_id']
    user = build_user(obj.pop('core')['user_results'])
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
                if 'additional_media_info' in media:
                    media['additional_media_info'].pop('source_user', None)

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

def build_timeline_user(obj):
    obj = obj['itemContent']
    assert obj['itemType'] == 'TimelineUser', obj['itemType']
    assert obj['__typename'] == 'TimelineUser', obj['__typename']
    assert obj['userDisplayType'] == 'User', obj['userDisplayType']
    obj = obj['user_results']
    return build_user(obj)

def build_timeline_tweet(obj):
    obj = obj['itemContent']
    # TODO: clientEventInfo
    assert obj['itemType'] == 'TimelineTweet', obj['itemType']
    assert obj['__typename'] == 'TimelineTweet', obj['__typename']
    assert obj['tweetDisplayType'] in ['Tweet', 'MediaGrid'], obj['tweetDisplayType']
    obj = obj['tweet_results']
    return build_tweet(obj)

def build_timeline_entry(obj):
    entry_id = obj["entryId"]
    if entry_id.startswith('tweet-'):
        obj = obj['content']
        assert obj['entryType'] == 'TimelineTimelineItem', obj['entryType']
        assert obj['__typename'] == 'TimelineTimelineItem', obj['__typename']
        ret = [build_timeline_tweet(obj)]
    elif entry_id.startswith('profile-conversation-'):
        obj = obj['content']
        assert obj['entryType'] == 'TimelineTimelineModule', obj['entryType']
        assert obj['__typename'] == 'TimelineTimelineModule', obj['__typename']
        items = obj['items']
        ret = []
        for obj in items:
            assert obj['entryId'].startswith('profile-conversation')
            obj = obj['item']
            ret.append(build_timeline_tweet(obj))
    elif entry_id.startswith('profile-grid-'):
        items = []
        if 'content' in obj:
            obj = obj['content']
            assert obj['entryType'] == 'TimelineTimelineModule', obj['entryType']
            assert obj['__typename'] == 'TimelineTimelineModule', obj['__typename']
            items = obj['items']
        if 'item' in obj:
            items.append(obj)
        ret = []
        for obj in items:
            assert obj['entryId'].startswith('profile-grid-')
            obj = obj['item']
            ret.append(build_timeline_tweet(obj))
    elif entry_id.startswith('user-'):
        obj = obj['content']
        assert obj['entryType'] == 'TimelineTimelineItem', obj['entryType']
        assert obj['__typename'] == 'TimelineTimelineItem', obj['__typename']
        ret = [build_timeline_user(obj)]
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