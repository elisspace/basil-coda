"""Official YouTube Music albums: fail closed on incomplete/unknown editions."""
import json
import re
import sqlite3
import subprocess
import time
from search_metadata import text, membership, parse_search
from discovery import connect, tune_key

ALBUM_PARAMS = 'EgWKAQIYAWoKEAkQBRAKEAMQBA%3D%3D'

def find(node,key):
    if isinstance(node,dict):
        if key in node: yield node[key]
        for value in node.values(): yield from find(value,key)
    elif isinstance(node,list):
        for value in node: yield from find(value,key)

def valid_browse(browse_id):
    if not re.fullmatch(r'MPREb_[A-Za-z0-9_-]{1,100}',browse_id):
        raise ValueError('Expected an official album browse ID, not a playlist or full-album video')

def search_albums(query):
    from djctl import api
    raw=api('POST','search',{'query':query,'params':ALBUM_PARAMS})
    result={}
    for kind in ('musicResponsiveListItemRenderer','musicTwoRowItemRenderer'):
        for row in find(raw,kind):
            endpoint=row.get('navigationEndpoint',{}).get('browseEndpoint',{})
            bid=endpoint.get('browseId','')
            if not re.fullmatch(r'MPREb_[A-Za-z0-9_-]{1,100}',bid): continue
            if endpoint.get('browseEndpointContextSupportedConfigs',{}).get('browseEndpointContextMusicConfig',{}).get('pageType') != 'MUSIC_PAGE_TYPE_ALBUM': continue
            columns=[text(c.get('musicResponsiveListItemFlexColumnRenderer',{}).get('text',{})) for c in row.get('flexColumns',[])]
            result[bid]={'browseId':bid,'title':text(row.get('title',{})) or (columns[0] if columns else ''),'subtitle':text(row.get('subtitle',{})) or ' | '.join(columns[1:])}
    return list(result.values())

def parse_album(raw,browse_id):
    valid_browse(browse_id)
    headers=list(find(raw,'musicResponsiveHeaderRenderer')) or list(find(raw,'musicDetailHeaderRenderer'))
    if len(headers)!=1: raise ValueError('Official album header unavailable')
    h=headers[0]
    if not any(run.get('text')=='Album' for run in h.get('subtitle',{}).get('runs',[])): raise ValueError('Not an official album')
    title=text(h.get('title',{})); artist=text(h.get('straplineTextOne',{}))
    if not artist:
        artist=''.join(run.get('text','') for run in h.get('subtitle',{}).get('runs',[]) if run.get('navigationEndpoint',{}).get('browseEndpoint',{}).get('browseId','').startswith('UC'))
    match=re.search(r'\b(\d+) songs?\b',text(h.get('secondSubtitle',{})))
    if not title or not artist or not match: raise ValueError('Cannot verify complete album count/artist')
    total=int(match.group(1))
    shelves=[s for kind in ('musicShelfRenderer','musicPlaylistShelfRenderer') for s in find(raw,kind) if any('musicResponsiveListItemRenderer' in x for x in s.get('contents',[]))]
    if len(shelves)!=1 or shelves[0].get('continuations'): raise ValueError('Cannot verify complete album; multiple shelves or continuation')
    tracks=[]; playlists=set()
    for number,item in enumerate(shelves[0].get('contents',[]),1):
        row=item.get('musicResponsiveListItemRenderer',{})
        vid=row.get('playlistItemData',{}).get('videoId','')
        columns=row.get('flexColumns',[])
        name=text(columns[0].get('musicResponsiveListItemFlexColumnRenderer',{}).get('text',{})) if columns else ''
        watches=list(find(row,'watchEndpoint'))
        official=[w for w in watches if w.get('videoId')==vid and w.get('playlistId','').startswith('OLAK5uy_') and w.get('watchEndpointMusicSupportedConfigs',{}).get('watchEndpointMusicConfig',{}).get('musicVideoType')=='MUSIC_VIDEO_TYPE_ATV']
        if not re.fullmatch(r'[A-Za-z0-9_-]{11}',vid) or not name or text(row.get('index',{}))!=str(number) or not official:
            raise ValueError('Cannot verify complete official album track order/availability')
        if row.get('musicItemRendererDisplayPolicy')=='MUSIC_ITEM_RENDERER_DISPLAY_POLICY_GREY_OUT': raise ValueError('Album contains unavailable track')
        playlists.update(w['playlistId'] for w in official)
        tracks.append({'number':number,'videoId':vid,'title':name,'artist':artist,**membership(row)})
    if not 2<=total<=100 or len(tracks)!=total or len(playlists)!=1 or len({t['videoId'] for t in tracks})!=total:
        raise ValueError('Cannot verify complete album; count/edition mismatch')
    return {'browseId':browse_id,'title':title,'artist':artist,'subtitle':text(h.get('subtitle',{})),'trackCount':total,'playlistId':next(iter(playlists)),'tracks':tracks}

def resolve_album(browse_id, screen=True):
    from djctl import SOURCE,api
    valid_browse(browse_id)
    raw=json.loads(subprocess.check_output(['node',str(SOURCE/'player_dom.mjs'),'album-browse',browse_id],text=True,timeout=15))
    album=parse_album(raw,browse_id)
    if screen:
        for track in album['tracks']:
            if track['library'] is None or track['liked'] is None:
                import os
                generation = os.environ.get('BASIL_REFILL_GENERATION')
                if generation:
                    from djctl import admit_refill
                    admit_refill(generation)
                results=parse_search(api('POST','search',{'query':track['artist']+' '+track['title']}))
                exact=next((r for r in results if r['videoId']==track['videoId']),None)
                if exact:
                    for flag in ('library','liked'):
                        # Never downgrade positive evidence from the album page.
                        if track[flag] is not True: track[flag]=exact[flag]
    return album

def reserve_album(path,tracks,current,avoid_repeats=True,exclude_library=True):
    from discovery import reserve_batch, eligible_queue, attempt_key
    if exclude_library and any(t.get('library') is not False or t.get('liked') is not False for t in tracks):
        raise ValueError('Entire album denied: library/liked membership true or unknown')
    ids=[t['videoId'] for t in tracks]; tunes=[tune_key(t['title']) for t in tracks]
    if len(set(ids))!=len(ids) or (avoid_repeats and len(set(tunes))!=len(tunes)): raise ValueError('Entire album denied: repeated tune within edition')
    if any(r['videoId'] in ids or (avoid_repeats and r.get('title') and tune_key(r['title']) in tunes) for r in eligible_queue(current,avoid_repeats)): raise ValueError('Entire album denied: track/tune already in queue')
    reserve_batch(path,tracks,avoid_repeats,attempt_key(current,ids))
