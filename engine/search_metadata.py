"""Search-only membership evidence. Missing or unrecognized evidence stays unknown."""
import contextlib
import sqlite3


def text(value):
    return ''.join(run.get('text', '') for run in value.get('runs', [])) if isinstance(value, dict) else ''


def membership(renderer):
    evidence = {'library': [], 'liked': []}
    def visit(node):
        if isinstance(node, dict):
            toggle = node.get('toggleMenuServiceItemRenderer')
            item = toggle or node.get('menuServiceItemRenderer')
            if isinstance(item, dict):
                label = text(item.get('defaultText') or item.get('text'))
                endpoint = item.get('defaultServiceEndpoint') or item.get('serviceEndpoint') or {}
                status = endpoint.get('likeEndpoint', {}).get('status')
                if label == 'Save to library' and isinstance(item.get('isToggled'), bool):
                    evidence['library'].append(item['isToggled'])
                if label == 'Remove from liked songs' and status == 'INDIFFERENT':
                    evidence['liked'].append(True)
                if label == 'Add to liked songs' and (item.get('defaultLikeStatus') == 'LIKE' or status == 'LIKE'):
                    evidence['liked'].append(False)
            for value in node.values(): visit(value)
        elif isinstance(node, list):
            for value in node: visit(value)
    # Restrict evidence to this result's own menu, never related card contents.
    visit(renderer.get('menu', {}))
    return {key: True if True in values else False if values else None for key, values in evidence.items()}


def parse_search(raw):
    result = {}
    def add(video_id, labels, renderer):
        if not video_id: return
        flags = membership(renderer)
        if video_id not in result:
            result[video_id] = {'videoId': video_id, 'labels': labels, **flags}
        else:
            previous = result[video_id]
            for key in flags:
                values = [previous[key], flags[key]]
                previous[key] = True if True in values else False if False in values else None
            if not previous['labels']: previous['labels'] = labels
    def visit(node):
        if isinstance(node, dict):
            card = node.get('musicCardShelfRenderer')
            if isinstance(card, dict):
                add(card.get('onTap', {}).get('watchEndpoint', {}).get('videoId'),
                    [text(card.get(k, {})) for k in ('title', 'subtitle')], card)
            row = node.get('musicResponsiveListItemRenderer')
            if isinstance(row, dict):
                add(row.get('playlistItemData', {}).get('videoId'),
                    [text(c.get('musicResponsiveListItemFlexColumnRenderer', {}).get('text', {})) for c in row.get('flexColumns', [])], row)
            for value in node.values(): visit(value)
        elif isinstance(node, list):
            for value in node: visit(value)
    visit(raw)
    return list(result.values())


def schema(db):
    db.execute('CREATE TABLE IF NOT EXISTS tracks (video_id TEXT PRIMARY KEY,title TEXT,artist TEXT,library INTEGER,liked INTEGER)')
    columns = {row[1] for row in db.execute('PRAGMA table_info(tracks)')}
    for column in ('library', 'liked'):
        if column not in columns:
            db.execute(f'ALTER TABLE tracks ADD COLUMN {column} INTEGER')


def cache_search(path, tracks):
    with contextlib.closing(sqlite3.connect(path)) as db, db:
        schema(db)
        for track in tracks:
            labels = track['labels']
            if labels and labels[0]:
                db.execute('INSERT OR REPLACE INTO tracks (video_id,title,artist,library,liked) VALUES (?,?,?,?,?)',
                           (track['videoId'], labels[0], ' | '.join(labels[1:]), track['library'], track['liked']))
            else:
                # Incomplete fresh results must not leave stale false flags usable.
                db.execute('UPDATE tracks SET library=?,liked=? WHERE video_id=?',
                           (track['library'], track['liked'], track['videoId']))


def cached_track(path, video_id):
    with contextlib.closing(sqlite3.connect(path)) as db, db:
        schema(db)
        return db.execute('SELECT title,artist,library,liked FROM tracks WHERE video_id=?', (video_id,)).fetchone()
