// Opt-in, generation-scoped observer and bounded maintenance. Self-contained for CDP.
// Never infer provenance from discovery reservations, library flags or queue size.
export function maintainQueueGuard(document, generation, expectedIds, deadlineMs) {
  const fail = () => { throw new Error('Queue guard refused; inspect queue, no automatic retry'); };
  const valid = id => typeof id === 'string' && /^[A-Za-z0-9_-]{11}$/.test(id);
  const renderer = item => item?.playlistPanelVideoRenderer || item?.playlistPanelVideoWrapperRenderer?.primaryRenderer?.playlistPanelVideoRenderer;
  const ids = items => {
    if (!Array.isArray(items) || items.length > 512) fail();
    const result = items.map(item => renderer(item)?.videoId);
    if (!result.every(valid) || new Set(result).size !== result.length) fail();
    return result;
  };
  const equal = (a,b) => a.length === b.length && a.every((x,i) => x === b[i]);
  const queue = document.querySelector('#queue');
  const store = queue?.queue?.store?.store;
  const video = document.querySelector('video');
  const admission = () => {
    const remaining = deadlineMs - Date.now();
    if (!Number.isSafeInteger(deadlineMs) || remaining <= 0 || remaining > 8000 || video?.paused !== false) fail();
  };
  if (!store?.getState || typeof store.dispatch !== 'function' || typeof generation !== 'string' || !generation || generation.length > 128) fail();
  if (!Array.isArray(expectedIds) || !expectedIds.every(valid)) fail();
  admission();
  const before = store.getState().queue;
  const beforeIds = ids(before?.items);
  if (!equal(beforeIds,expectedIds)) fail();
  const selected = before.items.map((x,i)=>renderer(x)?.selected ? i : -1).filter(i=>i>=0);
  if (selected.length !== 1) fail();
  const key = '__basilQueueGuardV1';
  let guard = store[key];
  if (guard && store.dispatch !== guard.wrapper) fail();
  if (!guard) {
    guard = {generation, tagged: new WeakSet(), observations: [], expected: beforeIds};
    const original = store.dispatch;
    // Observation only. Even after OFF this hook cannot suppress an action or
    // remove a row. Every actual removal needs a fresh locked 8-second lease.
    guard.wrapper = function(action) {
      const oldState = store.getState()?.queue;
      const oldItems = oldState?.items;
      const automix = oldState?.automixItems;
      const result = original.call(this, action);
      try {
        const newItems = store.getState()?.queue?.items;
        const oldIds = ids(oldItems), newIds = ids(newItems);
        if (!equal(oldIds,newIds)) {
          const tail = newItems.length > oldItems.length && oldIds.every((x,i)=>x===newIds[i]);
          const added = tail ? newItems.slice(oldItems.length) : [];
          // Real reducer: ADD_AUTOMIX_ITEMS changes only preview; the explicit
          // SHIFT_AUTOPLAY_ITEMS action promotes those rows into playable items.
          // Both action identity and pre-action preview membership are required.
          const supplied = action?.payload;
          const proven = action?.type === 'SHIFT_AUTOPLAY_ITEMS' && tail && added.length <= 100 &&
            Array.isArray(supplied) && supplied.length === added.length && Array.isArray(automix) &&
            added.every((x,i)=>x===supplied[i] && automix.includes(x));
          if (proven) added.forEach(x=>guard.tagged.add(x));
          // A manual move/replacement makes old row identity ambiguous; discard
          // all old proof. Unknown/manual additions are always left alone.
          if (!tail && action?.type !== 'REMOVE_ITEM') guard.tagged = new WeakSet();
          guard.observations.push({type:String(action?.type||'unknown').slice(0,64),beforeIds:oldIds,afterIds:newIds,proven});
          guard.observations = guard.observations.slice(-8);
          guard.expected = newIds;
        }
      } catch { guard.tagged = new WeakSet(); guard.expected = null; }
      return result;
    };
    store[key] = guard;
    store.dispatch = guard.wrapper;
  }
  if (guard.generation !== generation) {
    guard.generation = generation; guard.tagged = new WeakSet(); guard.observations = []; guard.expected = beforeIds;
  }
  // A queue replacement bypassing the observed dispatch invalidates all proof.
  if (!equal(guard.expected || [],beforeIds)) guard.tagged = new WeakSet();
  guard.expected = beforeIds;
  const removals = before.items.map((item,index)=>({item,index})).filter(({item,index})=>index>selected[0] && guard.tagged.has(item));
  if (removals.length > 100) fail();
  const removedIds = [];
  // Direct Redux edits cannot synchronize the server-backed ephemeral queue.
  // Shuffle can fetch RESET_SHUFFLE_ITEMS and resurrect removed/lose added rows.
  // Do not claim a safe repair unless the local queue is the verified authority.
  const blocked = queue.queue.serverQueuesEnabled !== false ? 'Server queue authority true/unknown; observe only' :
    before.shuffleEnabled !== false || before.repeatMode !== 'NONE' ? 'Shuffle/repeat unsafe or unknown; observe only' : null;
  if (blocked) return {generation,beforeIds,afterIds:beforeIds,removedIds,observations:guard.observations,blocked};
  for (const {item,index} of removals.reverse()) {
    admission();
    const current = store.getState().queue;
    if (queue.queue.serverQueuesEnabled !== false || current.shuffleEnabled !== false || current.repeatMode !== 'NONE') fail();
    if (current.items[index] !== item || renderer(item)?.selected) fail();
    const oldIds = ids(current.items);
    const currentSelection = current.items.find(x=>renderer(x)?.selected);
    const media = {time:video.currentTime,volume:video.volume,paused:video.paused};
    store.dispatch({type:'REMOVE_ITEM',payload:index});
    const after = store.getState().queue;
    if (!equal(ids(after.items),oldIds.filter((_,i)=>i!==index)) || after.items.find(x=>renderer(x)?.selected)!==currentSelection ||
        video.currentTime!==media.time || video.volume!==media.volume || video.paused!==media.paused) fail();
    removedIds.unshift(renderer(item).videoId);
  }
  return {generation,beforeIds,afterIds:ids(store.getState().queue.items),removedIds,observations:guard.observations};
}
