'use strict';
(() => {
  const $ = id => document.getElementById(id);
  let state = null, connected = false, chatBusy = false, chatAvailable = true, posting = false, mutating = false;
  let queueKey = '', chatKey = '', artKey = '', stateFlight = null, chatFlight = null;
  let chatTimer, gestureTimer, lastChatError = '';
  const greetings = [
    '“Eight arms, two turntables, and a rather unreasonable record collection.”',
    '“A good bassline is a handrail into unfamiliar territory.”',
    '“My waistcoat has no pockets. A terrible oversight for a record collector.”',
    '“Tell me a mood, a memory, or a chord you can’t quite forget.”',
    '“There’s no wrong door into music. Shall we try a side entrance?”'
  ];
  let greetingIndex = 0;
  let lastAudibleVolume = 50, volumeEditing = false;
  let historyEntries = [], historyFiltered = [], historyStart = 0, historyFlight = null;
  let historyLoaded = false, historyError = '', shortcutFocus = null, historyBestIndex = 0;
  const historyModel = globalThis.BasilHistory;
  function notice(message) { $('notice-text').textContent = message; $('notice').hidden = false; }
  async function request(path, body) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 15000);
    try {
      const response = await fetch(path, {
        method: body === undefined ? 'GET' : 'POST', cache: 'no-store', signal: controller.signal,
        headers: body === undefined ? { Accept: 'application/json' } : { Accept: 'application/json', 'Content-Type': 'application/json', 'X-Basil-Request': '1' },
        ...(body === undefined ? {} : { body: JSON.stringify(body) })
      });
      let data;
      try { data = await response.json(); } catch { throw new Error('The room returned an unreadable response. Please try again.'); }
      if (!response.ok || data.ok === false) throw new Error(data.error || `The request could not be completed (${response.status}).`);
      return data;
    } catch (error) {
      if (error.name === 'AbortError') throw new Error('The room took too long to respond. The request may still have arrived; refresh before retrying.');
      throw error;
    } finally { clearTimeout(timer); }
  }
  function time(value) {
    if (value === null || value === undefined || value === '' || !Number.isFinite(Number(value))) return '—:—';
    const n = Math.max(0, Math.floor(Number(value)));
    return `${Math.floor(n / 60)}:${String(n % 60).padStart(2, '0')}`;
  }
  function imageURL(value) {
    if (typeof value !== 'string' || !value.trim()) return null;
    try { const url = new URL(value, location.href); return ['http:', 'https:'].includes(url.protocol) ? url.href : null; } catch { return null; }
  }
  function mood() {
    const playing = connected && state?.live?.paused === false;
    $('basil').dataset.mood = chatBusy ? 'thinking' : playing ? 'playing' : 'idle';
    $('mood-label').textContent = chatBusy ? 'CONSIDERING YOUR REQUEST' : playing ? 'IN THE GROOVE' : 'AT YOUR SERVICE';
    $('thinking').hidden = chatAvailable && !chatBusy;
    $('thinking').textContent = chatAvailable ? 'Basil is considering your request …' : 'Conversation connection interrupted. Retrying…';
    $('send').disabled = posting || chatBusy;
    $('send').firstChild.textContent = posting ? 'Sending ' : chatBusy ? 'Thinking ' : 'Send ';
  }
  function controls() {
    const unavailable = !connected || mutating;
    const paused = state?.live?.paused;
    const volume = state?.volume?.volume;
    const validVolume = Number.isInteger(volume) && volume >= 0 && volume <= 100;
    $('volume').disabled = unavailable || !validVolume;
    $('mute').disabled = unavailable || !validVolume;
    if (validVolume && volume > 0) lastAudibleVolume = volume;
    if (!volumeEditing || unavailable) {
      if (validVolume) $('volume').value = String(volume);
      $('volume-value').textContent = connected && validVolume ? `${volume}%` : 'Unavailable';
    }
    $('mute').textContent = volume === 0 ? 'Restore' : 'Mute';
    $('mute').setAttribute('aria-label', volume === 0 ? `Restore volume to ${lastAudibleVolume}%` : 'Mute');
    $('mute').setAttribute('aria-pressed', String(validVolume && volume === 0));
    $('play-pause').disabled = unavailable || typeof paused !== 'boolean';
    $('next').disabled = unavailable || !state?.song;
    $('stop').disabled = unavailable || !(state?.session?.active || state?.song);
    const queueReady = state?.queue_capabilities?.refill === true;
    const savedOn = state?.session?.active === true;
    $('dj-toggle').disabled = mutating || !state || typeof state?.session?.active !== 'boolean' || (!queueReady && !savedOn);
    $('dj-toggle').textContent = !queueReady ? (savedOn ? 'Stop manager' : 'DJ unavailable') : savedOn ? 'DJ ON' : 'DJ OFF';
    $('dj-toggle').setAttribute('aria-pressed', String(queueReady && savedOn));
    const filters = state?.session?.effective_discovery_filters;
    for (const [id, key] of [['avoid-repeats','avoid_repeats'],['exclude-library','exclude_library']]) {
      $(id).disabled = unavailable || typeof filters?.[key] !== 'boolean';
      $(id).checked = filters?.[key] === true;
    }
    $('play-text').textContent = paused === false ? 'Pause' : 'Play';
    $('play-symbol').textContent = paused === false ? 'Ⅱ' : '▶';
    document.querySelectorAll('.queue-actions button').forEach(button => { button.disabled = unavailable || state?.queue_capabilities?.queue_edit !== true || button.dataset.boundary === 'true'; });
  }
  function drawQueue(entries) {
    const key = JSON.stringify(entries);
    if (key === queueKey) return;
    queueKey = key;
    const focused = document.activeElement?.dataset.focusKey;
    const scrollTop = $('queue').scrollTop;
    const fragment = document.createDocumentFragment();
    if (!entries.length) {
      const empty = document.createElement('li'); empty.className = 'queue-empty';
      empty.textContent = 'An empty record bag. Tell Basil where you’d like to go.'; fragment.append(empty);
    }
    entries.forEach((entry, position) => {
      const item = document.createElement('li'); item.className = 'queue-item';
      const number = document.createElement('span'); number.className = 'queue-number'; number.textContent = String(position + 1).padStart(2, '0');
      const cover = document.createElement('div'); cover.className = 'queue-art'; cover.setAttribute('aria-hidden', 'true'); cover.textContent = '♪';
      const src = imageURL(entry.imageSrc);
      if (src) { const img = document.createElement('img'); img.className = 'queue-art'; img.alt = ''; img.loading = 'lazy'; img.referrerPolicy = 'no-referrer'; img.src = src; img.addEventListener('error', () => img.remove(), { once: true }); cover.textContent = ''; cover.append(img); }
      const detail = document.createElement('div'); detail.className = 'queue-detail';
      const title = document.createElement('p'); title.className = 'queue-title'; title.textContent = entry.title || 'Untitled track';
      const artist = document.createElement('p'); artist.className = 'queue-artist'; artist.textContent = entry.artist || 'Artist not provided'; detail.append(title, artist);
      if (entry.selected) { const current = document.createElement('span'); current.className = 'queue-selected'; current.textContent = 'ON THE TURNTABLE'; detail.append(current); }
      const actions = document.createElement('div'); actions.className = 'queue-actions';
      [['up', '↑', 'Move up'], ['down', '↓', 'Move down'], ['remove', '×', 'Remove']].forEach(([action, symbol, label]) => {
        const button = document.createElement('button'); button.type = 'button'; button.textContent = symbol;
        button.setAttribute('aria-label', `${label}: ${entry.title || 'untitled track'}`); button.title = label;
        button.dataset.focusKey = `${entry.videoId || entry.index}:${action}`;
        button.dataset.boundary = String(action === 'up' && position === 0 || action === 'down' && position === entries.length - 1);
        button.addEventListener('click', () => editQueue(entry, action, entries[action === 'up' ? position - 1 : position + 1]));
        actions.append(button);
      });
      item.append(number, cover, detail, actions); fragment.append(item);
    });
    $('queue').replaceChildren(fragment); $('queue').scrollTop = scrollTop;
    $('queue-count').textContent = `(${entries.length})`;
    if (focused) { const button = Array.from(document.querySelectorAll('[data-focus-key]')).find(el => el.dataset.focusKey === focused); if (button) button.focus({ preventScroll: true }); else $('queue-heading').setAttribute('tabindex', '-1'), $('queue-heading').focus({ preventScroll: true }); }
  }
  function renderState(data) {
    state = data; connected = true;
    $('connection').textContent = 'Connected to the room'; $('connection-dot').className = 'status-dot online';
    const song = data.song, live = data.live || {};
    $('song-title').textContent = song?.title || (song ? 'Untitled track' : 'Nothing on the turntable.');
    $('song-artist').textContent = song ? song.artist || 'Artist not provided' : 'Ask Basil to find your first record.';
    $('song-album').textContent = typeof song?.album === 'string' ? song.album : '';
    $('playback-label').textContent = live.paused === true ? 'PAUSED' : live.paused === false ? 'PLAYING' : 'NO PLAYBACK SIGNAL';
    const src = imageURL(song?.imageSrc);
    if (src !== artKey) {
      artKey = src; $('album-art').hidden = true; $('art-placeholder').hidden = false;
      if (src) {
        $('album-art').onload = () => { $('album-art').hidden = false; $('art-placeholder').hidden = true; };
        $('album-art').onerror = () => { $('album-art').hidden = true; $('art-placeholder').hidden = false; };
        $('album-art').alt = `Cover art for ${song?.title || 'the current record'}`;
        $('album-art').referrerPolicy = 'no-referrer'; $('album-art').src = src;
      } else $('album-art').removeAttribute('src');
    }
    $('elapsed').textContent = time(live.currentTime); $('duration').textContent = time(live.duration);
    const ratio = Number(live.duration) > 0 && Number.isFinite(Number(live.currentTime)) ? Math.max(0, Math.min(100, Number(live.currentTime) / Number(live.duration) * 100)) : 0;
    $('progress-fill').style.width = `${ratio}%`; $('progress').setAttribute('aria-valuenow', String(Math.round(ratio)));
    $('progress').setAttribute('aria-valuetext', `${time(live.currentTime)} of ${time(live.duration)}`);
    const active = data.session?.active;
    const nextCheck = data.session?.next_check;
    const checkText = active && Number.isFinite(nextCheck) ? ` · Next check ${new Date(nextCheck * 1000).toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'})}` : '';
    const queueReady = data.queue_capabilities?.refill === true;
    $('session-status').textContent = !queueReady
      ? (data.queue_capabilities?.reason || 'Queue automation unavailable; transport and read-only controls remain separate.')
      : `${active === true ? 'DJ ON until OFF' : active === false ? 'DJ OFF' : 'DJ status unavailable'} · ${data.worker_running === true ? 'Worker online' : data.worker_running === false ? 'Worker offline' : 'Worker unknown'}${active && live.paused === true ? ' · Paused: no refills' : ''}${checkText}${data.session?.error ? ' · ' + data.session.error : ''}`;
    $('session-dot').className = `status-dot${queueReady && active ? ' online' : ''}`;
    $('session-brief').textContent = typeof data.session?.brief === 'string' ? data.session.brief : '';
    $('session-brief').hidden = !$('session-brief').textContent;
    const queue = Array.isArray(data.queue) ? data.queue : [];
    const selected = queue.filter(entry => entry.selected);
    // Show the editable future, not the player's accumulated listening history.
    const upcoming = selected.length === 1 ? queue.filter(entry => entry.index > selected[0].index) : [];
    drawQueue(upcoming); controls(); mood();
  }
  function refreshState() {
    if (stateFlight) return stateFlight;
    stateFlight = request('/api/state').then(data => { renderState(data); return true; }).catch(() => {
      connected = false; $('connection').textContent = state ? 'Connection lost · showing last update' : 'The room is unreachable · retrying';
      $('connection-dot').className = 'status-dot error'; $('playback-label').textContent = 'SIGNAL UNAVAILABLE';
      $('session-status').textContent = 'Live DJ status unavailable · Run basil-coda doctor. Install/configure Pear and Hermes separately, then explicitly open and sign in to the dedicated player. Serving this page does not start music.';
      $('session-dot').className = 'status-dot error';
      if (!state) { $('song-artist').textContent = 'Waiting to reconnect to the music service'; $('queue').firstElementChild.textContent = 'The record bag is unavailable while disconnected.'; }
      controls(); mood(); return false;
    }).finally(() => { stateFlight = null; });
    return stateFlight;
  }
  function renderChat(data) {
    const messages = Array.isArray(data.messages) ? data.messages.filter(m => ['assistant', 'user'].includes(m.role) && typeof m.content === 'string') : [];
    const key = JSON.stringify(messages);
    if (key !== chatKey) {
      chatKey = key;
      const box = $('chat-messages'), nearBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 65;
      if (messages.length) {
        const fragment = document.createDocumentFragment();
        messages.forEach(message => {
          const article = document.createElement('article'); article.className = `chat-message ${message.role}`;
          const speaker = document.createElement('span'); speaker.className = 'speaker'; speaker.textContent = message.role === 'assistant' ? 'BASIL CODA' : 'YOU';
          const content = document.createElement('p'); content.textContent = message.content; article.append(speaker, content); fragment.append(article);
        }); box.replaceChildren(fragment);
      } else { const empty = document.createElement('p'); empty.className = 'chat-empty'; empty.textContent = 'A place, a feeling, a favourite record. Give Basil a thread to follow.'; box.replaceChildren(empty); }
      if (nearBottom) box.scrollTop = box.scrollHeight;
    }
    if (data.error && data.error !== lastChatError) notice(data.error);
    lastChatError = data.error || '';
    chatBusy = data.busy === true; mood();
  }
  function refreshChat() {
    if (chatFlight) return chatFlight;
    clearTimeout(chatTimer);
    chatFlight = request('/api/chat').then(data => { chatAvailable = true; renderChat(data); return true; }).catch(() => {
      chatAvailable = false; mood(); return false;
    }).finally(() => { chatFlight = null; chatTimer = setTimeout(refreshChat, chatBusy ? 1500 : 4000); });
    return chatFlight;
  }
  async function mutation(path, body) {
    if (mutating || !connected) return;
    mutating = true; controls();
    try {
      await request(path, body);
      // Await any older read, then fetch fresh authoritative state after the write.
      if (stateFlight) await stateFlight;
      if (!await refreshState()) notice('The request was accepted, but its result could not be verified. Waiting to reconnect.');
    } catch (error) { notice(error.message || 'The request failed. Please try again.'); }
    finally { mutating = false; controls(); }
  }
  function editQueue(entry, action, target) {
    if (action !== 'remove' && !target) return;
    mutation(`/api/queue/${action === 'remove' ? 'remove' : 'move'}`, { videoId: entry.videoId, index: entry.index, ...(action === 'remove' ? {} : { toIndex: target.index }) });
  }
  function setVolume(value) {
    if ($('volume').disabled) return;
    return mutation('/api/volume', {volume: Math.max(0, Math.min(100, Math.round(value)))});
  }
  $('volume').addEventListener('input', () => {
    volumeEditing = true;
    $('volume-value').textContent = `${$('volume').value}%`;
  });
  $('volume').addEventListener('change', async () => {
    const value = Number($('volume').value);
    volumeEditing = false;
    await setVolume(value);
    controls();
  });
  $('volume').addEventListener('blur', () => { volumeEditing = false; controls(); });
  $('mute').addEventListener('click', () => setVolume(state?.volume?.volume === 0 ? lastAudibleVolume : 0));

  const historyDate = timestamp => new Date(timestamp * 1000).toLocaleDateString(undefined, {year:'numeric', month:'short', day:'numeric'});
  function drawHistory(syncRail = true) {
    const entries = historyFiltered, total = entries.length;
    historyStart = Math.max(0, Math.min(historyStart, Math.max(0, total - 1)));
    const end = Math.min(total, historyStart + historyModel.PAGE_SIZE);
    const fragment = document.createDocumentFragment();
    let lastDay = '';
    for (let index = historyStart; index < end; index++) {
      const entry = entries[index], day = historyDate(entry.timestamp);
      if (day !== lastDay) {
        const group = document.createElement('li'); group.className = 'history-day';
        const heading = document.createElement('h3'); heading.textContent = day;
        group.append(heading); fragment.append(group); lastDay = day;
      }
      const item = document.createElement('li'); item.className = 'history-item';
      const art = document.createElement('div'); art.className = 'queue-art'; art.setAttribute('aria-hidden', 'true'); art.textContent = '♪';
      const src = imageURL(entry.imageSrc);
      if (src) {
        const img = document.createElement('img'); img.alt = ''; img.loading = 'lazy'; img.referrerPolicy = 'no-referrer'; img.src = src;
        img.addEventListener('error', () => img.remove(), {once:true}); art.append(img);
      }
      const detail = document.createElement('div'); detail.className = 'queue-detail';
      const title = document.createElement('p'); title.className = 'queue-title'; title.textContent = entry.title || 'Untitled track';
      const artist = document.createElement('p'); artist.className = 'queue-artist'; artist.textContent = entry.artist || 'Artist not provided';
      detail.append(title, artist);
      const status = document.createElement('span'); status.className = `history-kind ${entry.status}`;
      status.textContent = entry.status === 'played' ? 'Observed playback' : 'Queued · not confirmed played';
      const stamp = document.createElement('time'); stamp.dateTime = new Date(entry.timestamp * 1000).toISOString();
      stamp.textContent = new Date(entry.timestamp * 1000).toLocaleTimeString(undefined, {hour:'2-digit', minute:'2-digit'});
      const meta = document.createElement('div'); meta.className = 'history-meta'; meta.append(status, stamp);
      item.append(art, detail, meta); fragment.append(item);
    }
    $('history-list').replaceChildren(fragment);
    $('history-list').scrollTop = 0;
    $('history-status').textContent = historyError ? `${historyError}${historyLoaded ? ' Showing the last loaded ledger.' : ''} Use Refresh history to retry.` : total ? `${total.toLocaleString()} records · newest first · dates in your local time` : historyEntries.length ? 'No records match. Try fewer letters or another record type.' : historyLoaded ? 'No records in the ledger yet. New observations will appear here.' : 'Opening the record ledger…';
    $('history-page').textContent = total ? `${historyStart + 1}–${end} of ${total.toLocaleString()}` : '';
    $('history-newer').disabled = historyStart === 0;
    $('history-older').disabled = end >= total;
    $('history-scrubber').disabled = total < 2 || entries[0]?.timestamp === entries.at(-1)?.timestamp;
    $('history-newest').textContent = total ? historyDate(entries[0].timestamp) : 'Newest';
    $('history-oldest').textContent = total ? historyDate(entries.at(-1).timestamp) : 'Oldest';
    const current = entries[historyStart];
    $('history-position').textContent = current ? `— ${historyDate(current.timestamp)}` : '';
    $('history-scrubber').setAttribute('aria-valuetext', current ? historyDate(current.timestamp) : 'No records');
    if (syncRail) {
      const span = total ? entries[0].timestamp - entries.at(-1).timestamp : 0;
      $('history-scrubber').value = String(span ? Math.round((entries[0].timestamp - current.timestamp) / span * 1000) : 0);
    }
  }
  function filterHistory() {
    const kind = $('history-kind').value;
    historyFiltered = historyModel.filter(historyEntries.filter(entry => kind === 'all' || kind === entry.status), $('history-search').value);
    historyBestIndex = 0;
    if ($('history-search').value.trim() && historyFiltered.length) {
      let bestScore = -1;
      historyFiltered.forEach((entry, index) => { const score = historyModel.rank(entry, $('history-search').value); if (score > bestScore) { bestScore = score; historyBestIndex = index; } });
      const best = historyFiltered[historyBestIndex];
      $('history-best').textContent = `Best match: ${best.title || 'Untitled track'} — ${best.artist || 'Artist not provided'} · Jump to record ↗`;
      $('history-best').hidden = false;
    } else $('history-best').hidden = true;
    historyStart = 0; drawHistory();
  }
  function refreshHistory() {
    if (historyFlight) return historyFlight;
    $('history-refresh').disabled = true;
    $('history-status').textContent = 'Refreshing the record ledger…';
    historyFlight = request('/api/history').then(data => {
      if (!Array.isArray(data.entries)) throw new Error('The ledger returned an unreadable response.');
      const anchor = historyFiltered[historyStart]?.id;
      historyEntries = historyModel.prepare(data.entries); historyLoaded = true; historyError = '';
      $('history-coverage').textContent = `${typeof data.coverage === 'string' ? data.coverage + ' ' : ''}Observed playback is not a completed-listen count. Queue reservations are not proof of listening.`;
      filterHistory();
      if (anchor) { const index = historyFiltered.findIndex(entry => entry.id === anchor); if (index >= 0) { historyStart = index; drawHistory(); } }
    }).catch(error => { historyError = error.message || 'The ledger is unavailable.'; drawHistory(); })
      .finally(() => { historyFlight = null; $('history-refresh').disabled = false; });
    return historyFlight;
  }
  $('history-best').addEventListener('click', () => { historyStart = historyBestIndex; drawHistory(); });
  $('history-search').addEventListener('input', filterHistory);
  $('history-kind').addEventListener('change', filterHistory);
  $('history-refresh').addEventListener('click', refreshHistory);
  $('history-scrubber').addEventListener('input', () => { historyStart = historyModel.timeIndex(historyFiltered, $('history-scrubber').value); drawHistory(false); });
  $('history-newer').addEventListener('click', () => { historyStart = Math.max(0, historyStart - historyModel.PAGE_SIZE); drawHistory(); });
  $('history-older').addEventListener('click', () => { historyStart += historyModel.PAGE_SIZE; drawHistory(); });

  function openShortcuts() {
    if ($('shortcuts').open) return;
    shortcutFocus = document.activeElement;
    $('shortcuts').showModal();
  }
  $('shortcuts-open').addEventListener('click', openShortcuts);
  $('shortcuts-close').addEventListener('click', () => $('shortcuts').close());
  $('shortcuts').addEventListener('close', () => { shortcutFocus?.focus({preventScroll:true}); });
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && $('shortcuts').open) { event.preventDefault(); $('shortcuts').close(); return; }
    // The guide has one interactive element. Keep Tab/Shift+Tab inside it,
    // including browsers that otherwise send a lone dialog button to chrome.
    if ($('shortcuts').open && event.key === 'Tab' && !event.ctrlKey && !event.metaKey && !event.altKey) {
      event.preventDefault(); $('shortcuts-close').focus(); return;
    }
    if (event.defaultPrevented || event.isComposing || event.repeat || event.ctrlKey || event.metaKey || event.altKey || $('shortcuts').open) return;
    const target = event.target;
    if (target?.isContentEditable || target?.closest?.('input, textarea, select, [contenteditable="true"], [role="textbox"]')) return;
    // Native button/link activation takes precedence over transport shortcuts.
    if (event.key === ' ' && target?.closest?.('button, a, summary, [role="button"]')) return;
    if (event.shiftKey && !['?', '+'].includes(event.key)) return;
    const key = event.key.toLowerCase();
    const button = key === ' ' ? $('play-pause') : key === 'n' ? $('next') : key === 'm' ? $('mute') : null;
    if (button) { if (button.disabled) return; event.preventDefault(); button.click(); }
    else if (key === '+' || key === '=' || key === '-') {
      if ($('volume').disabled) return;
      event.preventDefault(); setVolume(state.volume.volume + (key === '-' ? -5 : 5));
    } else if (key === '/' || key === 'h') {
      event.preventDefault(); $('history-section').scrollIntoView({block:'start'});
      $(key === '/' ? 'history-search' : 'history-heading').focus({preventScroll:true});
    } else if (key === '?') { event.preventDefault(); openShortcuts(); }
  });
  $('play-pause').addEventListener('click', () => mutation('/api/control', { action: state?.live?.paused ? 'play' : 'pause' }));
  $('next').addEventListener('click', () => mutation('/api/control', { action: 'next' }));
  $('stop').addEventListener('click', () => mutation('/api/control', { action: 'stop' }));
  $('dj-toggle').addEventListener('click', () => mutation('/api/control', { action: state?.session?.active ? 'dj_off' : 'dj_on' }));
  $('avoid-repeats').addEventListener('change', () => mutation('/api/settings', { avoid_repeats: $('avoid-repeats').checked }));
  $('exclude-library').addEventListener('change', () => mutation('/api/settings', { exclude_library: $('exclude-library').checked }));
  $('dismiss-notice').addEventListener('click', () => { $('notice').hidden = true; });
  $('basil').addEventListener('click', () => {
    $('basil-speech').textContent = greetings[greetingIndex++ % greetings.length];
    clearTimeout(gestureTimer); $('basil').classList.remove('gesturing');
    void $('basil').offsetWidth; $('basil').classList.add('gesturing'); gestureTimer = setTimeout(() => $('basil').classList.remove('gesturing'), 1900);
  });
  document.querySelectorAll('[data-prompt]').forEach(button => button.addEventListener('click', () => { $('message').value = button.dataset.prompt; $('message').focus(); }));
  $('message').addEventListener('keydown', event => { if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) { event.preventDefault(); if (!posting && !chatBusy) $('chat-form').requestSubmit(); } });
  $('chat-form').addEventListener('submit', async event => {
    event.preventDefault(); const text = $('message').value.trim(); if (!text || posting || chatBusy) return;
    posting = true; mood();
    try {
      await request('/api/chat', { message: text });
      // Deduplicate polls, not failures belonging to a new accepted request.
      lastChatError = '';
      if ($('message').value.trim() === text) $('message').value = '';
      if (chatFlight) await chatFlight;
      if (!await refreshChat()) notice('Your message was accepted. The conversation is unavailable until the connection returns.');
      await refreshState();
    } catch (error) { notice(error.message || 'Your message could not be sent.'); }
    finally { posting = false; mood(); $('message').focus(); }
  });
  async function pollState() { await refreshState(); setTimeout(pollState, document.hidden ? 10000 : 2500); }
  document.addEventListener('visibilitychange', () => { if (!document.hidden) { refreshState(); refreshChat(); } });
  pollState(); refreshChat(); refreshHistory();
})();
