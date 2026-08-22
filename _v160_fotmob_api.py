# -*- coding: utf-8 -*-
import json, requests
UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
      'Referer': 'https://www.fotmob.com/'}
for mid in ('5795369', '5795363'):
    for url in ('https://www.fotmob.com/api/matchDetails?matchId=%s' % mid,
                'https://www.fotmob.com/api/data/matchDetails?matchId=%s' % mid):
        try:
            r = requests.get(url, headers=UA, timeout=25)
            print(mid, url.split('/api/')[1][:30], '->', r.status_code, len(r.text), r.text[:120].replace('\n',' '))
        except Exception as e:
            print(mid, url, 'ERR', type(e).__name__, e)
