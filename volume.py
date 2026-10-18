"""Fixed Pear volume endpoint helpers; injectable transport for isolated tests.

The live /doc schema returns {state: number, isMuted: boolean} for GET volume,
not {volume: number}. The web API exposes the setting as {volume: int}.
"""
import math


def read_volume(api, error):
    raw = api('GET', 'volume')
    value = raw.get('state') if isinstance(raw, dict) else None
    if (not isinstance(value, (int, float)) or isinstance(value, bool) or
            not 0 <= value <= 100 or not math.isfinite(value) or int(value) != value):
        raise error(502, 'Player returned an invalid volume setting.')
    return {'volume': int(value)}


def set_volume(app, body, api, error):
    """Use Application's admission, mutation lock, player lock, and poller.

    api must be authenticated djctl.api; callers cannot supply a path or method.
    No automatic retry of POST, including when read-back is unconfirmed.
    """
    value = body.get('volume') if isinstance(body, dict) else None
    if type(value) is not int or not 0 <= value <= 100:
        raise error(400, 'volume must be an integer from 0 to 100.')
    app.acquire_mutation()
    try:
        with app.player_lock:
            api('POST', 'volume', {'volume': value})
            confirmed = app.poll(lambda: read_volume(api, error),
                                 lambda result: result['volume'] == value)
            return {'ok': True, **confirmed}
    finally:
        try:
            app.invalidate()
        finally:
            app.mutation_lock.release()
