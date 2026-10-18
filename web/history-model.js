'use strict';
// Pure history operations, shared by the interface and dependency-free tests.
globalThis.BasilHistory = (() => {
  const PAGE_SIZE = 60;
  const normalize = value => String(value || '').normalize('NFD').replace(/\p{M}/gu, '').toLocaleLowerCase().replace(/[^\p{L}\p{N}]+/gu, ' ').trim();
  function rank(entry, query) {
    const tokens = normalize(query).split(/\s+/).filter(Boolean);
    const text = entry.searchText ?? normalize(`${entry.title || ''} ${entry.artist || ''}`);
    let score = 1;
    for (const token of tokens) {
      const exact = text.indexOf(token);
      if (exact >= 0) { score += 100 + token.length * 5 - Math.min(exact, 50); continue; }
      let cursor = -1, first = -1;
      for (const letter of token) {
        cursor = text.indexOf(letter, cursor + 1);
        if (cursor < 0) return 0;
        if (first < 0) first = cursor;
      }
      score += 1 + token.length / (cursor - first + 1);
    }
    return score;
  }
  function prepare(entries) {
    return entries.filter(e => e && typeof e.timestamp === 'number' && Number.isFinite(e.timestamp) && Math.abs(e.timestamp) <= 8640000000000 && ['played', 'queued'].includes(e.status))
      .map(e => ({...e, searchText: normalize(`${e.title || ''} ${e.artist || ''}`)}))
      .sort((a, b) => b.timestamp - a.timestamp);
  }
  function filter(entries, query) {
    // Chronology remains primary so the time rail is predictable; relevance breaks ties.
    return entries.map(entry => ({entry, score: rank(entry, query)})).filter(hit => hit.score > 0)
      .sort((a, b) => b.entry.timestamp - a.entry.timestamp || b.score - a.score).map(hit => hit.entry);
  }
  function timeIndex(entries, position) {
    if (entries.length < 2) return 0;
    const target = entries[0].timestamp - (entries[0].timestamp - entries.at(-1).timestamp) * Math.max(0, Math.min(1000, Number(position))) / 1000;
    let low = 0, high = entries.length - 1;
    while (low < high) { const mid = Math.floor((low + high) / 2); if (entries[mid].timestamp > target) low = mid + 1; else high = mid; }
    return low > 0 && Math.abs(entries[low - 1].timestamp - target) < Math.abs(entries[low].timestamp - target) ? low - 1 : low;
  }
  return {PAGE_SIZE, rank, prepare, filter, timeIndex};
})();
