// Self-contained so the fixed function can run in the dedicated renderer via CDP.
// No user-supplied expressions, credentials, IPC, or library mutations.
export async function appendAlbum(document, videoIds, expectedIds, deadlineMs, requirePlaying = true, replayIndex = null) {
  const valid = id => typeof id === 'string' && /^[A-Za-z0-9_-]{11}$/.test(id);
  const fail = () => { throw new Error('Exact queue append refused; inspect queue, do not retry automatically'); };
  if (!Array.isArray(videoIds) || videoIds.length < 2 || videoIds.length > 100 || !videoIds.every(valid) || new Set(videoIds).size !== videoIds.length || !Array.isArray(expectedIds) || !expectedIds.every(valid)) fail();
  const renderer = item => item?.playlistPanelVideoRenderer || item?.playlistPanelVideoWrapperRenderer?.primaryRenderer?.playlistPanelVideoRenderer;
  const ids = items => {
    if (!Array.isArray(items)) fail();
    const result = items.map(item => renderer(item)?.videoId);
    if (!result.every(valid)) fail();
    return result;
  };
  const equal = (a, b) => a.length === b.length && a.every((id, i) => id === b[i]);
  const queue = document.querySelector('#queue');
  const app = document.querySelector('ytmusic-app');
  const store = queue?.queue?.store?.store;
  if (!store?.getState || typeof queue?.dispatch !== 'function' || typeof app?.networkManager?.fetch !== 'function') fail();
  const before = store.getState().queue;
  // Shuffle uses a separately server-backed queue on current YTM builds. Local
  // appends during shuffle can disappear when its remote queue is restored.
  if (before?.shuffleEnabled !== false) fail();
  const beforeIds = ids(before?.items);
  if (replayIndex !== null && (!Number.isInteger(replayIndex) || replayIndex < 0 || replayIndex >= beforeIds.length || before.selectedItemIndex !== replayIndex)) fail();
  if (!equal(beforeIds, expectedIds) || videoIds.some(id => beforeIds.slice(replayIndex ?? 0).includes(id))) fail();
  // Absolute admission expiry is minted before CDP submission. A disconnected
  // client cannot extend it, and delayed Runtime.evaluate starts fail closed.
  const remaining = deadlineMs - Date.now();
  if (!Number.isSafeInteger(deadlineMs) || remaining <= 0 || remaining > 8000 || typeof requirePlaying !== 'boolean') fail();
  const playing = () => !requirePlaying || document.querySelector('video')?.paused === false;
  if (!playing()) fail();
  let expired = false;
  const timer = setTimeout(() => { expired = true; }, remaining);
  try {
  const response = await app.networkManager.fetch('/music/get_queue', {
    queueContextParams: before.queueContextParams,
    queueInsertPosition: 'INSERT_AT_END', videoIds
  });
  if (!Array.isArray(response?.queueDatas)) fail();
  const requested = videoIds.map(id => {
    const matches = response.queueDatas.map(row => row?.content).filter(item => renderer(item)?.videoId === id);
    if (matches.length !== 1) fail();
    return matches[0];
  });
  const current = store.getState().queue;
  // Abort if the queue changes during the async fetch; never replace or clean it.
  if (current.items !== before.items || !equal(ids(current.items), beforeIds) || (replayIndex !== null && current.selectedItemIndex !== replayIndex)) fail();
  // Last synchronous admission immediately before the only mutation. Do not
  // rely on native fetch abort or CDP/socket lifetime to cancel renderer work.
  if (expired || Date.now() >= deadlineMs || !playing() || current.shuffleEnabled !== false) fail();
  queue.dispatch({type: 'ADD_ITEMS', payload: {
    nextQueueItemId: current.nextQueueItemId, index: current.items.length,
    items: requested, shuffleEnabled: false, shouldAssignIds: true
  }});
  const afterIds = ids(store.getState().queue.items);
  if (!equal(afterIds, [...beforeIds, ...videoIds])) fail();
  return {beforeIds, afterIds, insertedVideoIds: videoIds};
  } finally { clearTimeout(timer); }
}
