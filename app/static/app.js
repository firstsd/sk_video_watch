const $ = (id) => document.getElementById(id);
const names = {streamed: 'Streamed', streamfree: 'StreamFree', fsl: 'FSL'};
let matches = [], sportView = 'arsenal', selected = null, sources = [], sourceIndex = 0;
let selectionRequest = 0, listingRequest = 0;
let playbackRequest = 0;
let resolvingVideo = null;
const directPlayer = new DirectPlayer();
const dateFormat = new Intl.DateTimeFormat('en-US', {timeZone: 'America/Los_Angeles', month: 'short', day: 'numeric'});
const timeFormat = new Intl.DateTimeFormat('en-US', {timeZone: 'America/Los_Angeles', hour: 'numeric', minute: '2-digit', timeZoneName: 'short'});

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

async function getJSON(url) {
  const response = await fetch(url, {signal: AbortSignal.timeout(45000)});
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || `Request failed (${response.status})`);
  }
  return response.json();
}

function renderMatches() {
  const search = $('search').value.trim().toLowerCase();
  const provider = $('provider').value;
  const filtered = matches.filter(m =>
    (sportView === 'arsenal' ? m.sport === 'football' && /\barsenal\b/i.test(m.title)
      : sportView === 'nba' ? m.sport === 'basketball' : m.sport === 'football') &&
    (!provider || m.provider === provider) && `${m.title} ${m.league}`.toLowerCase().includes(search));
  $('matches').replaceChildren();
  $('result-count').textContent = `${filtered.length} listing${filtered.length === 1 ? '' : 's'} · availability varies by source`;
  if (!filtered.length) {
    const box = element('div', 'empty', sportView === 'arsenal'
      ? 'No Arsenal matches in the current provider listings. These feeds are not a complete season schedule.'
      : `No ${sportView === 'nba' ? 'NBA games' : 'football matches'} found. Try another filter or check the provider status below.`);
    if (sportView === 'arsenal') {
      box.append(element('br'));
      const button = element('button', '', 'Browse all football');
      button.addEventListener('click', () => setSport('football'));
      box.append(button);
    }
    $('matches').append(box);
  }
  for (const match of filtered) {
    const row = element('article', `match${selected?.id === match.id ? ' selected' : ''}`);
    const kickoff = element('div', 'kickoff');
    if (match.starts_at) {
      const date = new Date(match.starts_at * 1000);
      kickoff.append(element('strong', '', dateFormat.format(date)), document.createTextNode(timeFormat.format(date)));
    } else kickoff.textContent = 'Time unavailable';
    const details = element('div');
    details.append(element('h3', 'match-title', match.title), element('span', 'competition', match.league));
    const watch = element('button', '', selected?.id === match.id ? 'Selected' : 'Watch →');
    watch.setAttribute('aria-label', `Watch ${match.title} on ${names[match.provider]}`);
    watch.addEventListener('click', () => selectMatch(match));
    const thumbnail = element('div', `match-art art-${match.sport}`);
    thumbnail.setAttribute('aria-hidden', 'true');
    thumbnail.append(element('span', 'art-league', match.league || 'FOOTBALL'), element('span', 'art-play', '▶'), element('span', 'art-provider', names[match.provider]));
    row.append(thumbnail, kickoff, details, element('span', 'provider-name', names[match.provider]), watch);
    $('matches').append(row);
  }
}

function setSport(view) {
  sportView = view;
  $('arsenal').setAttribute('aria-pressed', String(view === 'arsenal'));
  $('football').setAttribute('aria-pressed', String(view === 'football'));
  $('nba').setAttribute('aria-pressed', String(view === 'nba'));
  renderMatches();
}

async function loadMatches() {
  const request = ++listingRequest;
  $('refresh').disabled = true;
  $('matches').setAttribute('aria-busy', 'true');
  try {
    const data = await getJSON('/api/matches');
    if (request !== listingRequest) return;
    matches = data.matches;
    renderMatches();
    $('provider-status').replaceChildren();
    for (const provider of data.providers) {
      const link = element('a', `provider-chip${provider.error ? ' error' : ''}`,
        `${provider.name}: ${provider.error || `${provider.count} listings`}`);
      link.href = provider.url;
      link.target = '_blank';
      link.rel = 'noopener noreferrer';
      $('provider-status').append(link);
    }
    $('updated').textContent = `Fetched ${timeFormat.format(new Date(data.fetched_at))}. Listings cached for 60 seconds; source results for 30 seconds. Kickoff times and titles are supplied by the providers.`;
  } catch (error) {
    $('result-count').textContent = `Could not refresh: ${error.message}`;
    if (!matches.length) $('matches').replaceChildren(element('div', 'empty', 'The app could not load listings. Use Refresh listings to try again.'));
  } finally {
    $('refresh').disabled = false;
    $('matches').setAttribute('aria-busy', 'false');
  }
}

function clearPlayer(message) {
  playbackRequest++;
  directPlayer.stop();
  const placeholder = element('div', 'placeholder');
  placeholder.append(element('h2', '', message));
  $('screen').replaceChildren(placeholder);
  $('stop-player').disabled = true;
}

async function selectMatch(match) {
  const request = ++selectionRequest;
  const previousSource = selected?.id === match.id ? sources[sourceIndex]?.url : null;
  $('watch-room').hidden = false;
  selected = match;
  sources = [];
  sourceIndex = 0;
  clearPlayer('Finding available sources…');
  $('watch-title').textContent = match.title;
  $('watch-provider').textContent = `Provider · ${names[match.provider]}`;
  $('watch-source').hidden = true;
  $('watch-source').textContent = '';
  $('player-status').textContent = `Checking ${names[match.provider]}…`;
  $('original').href = match.page_url;
  $('original').hidden = false;
  $('source-select').replaceChildren(element('option', '', 'Checking sources…'));
  $('source-select').disabled = true;
  $('reload-player').disabled = true;
  $('next-source').disabled = true;
  renderMatches();
  $('screen').scrollIntoView({behavior: 'smooth', block: 'start'});
  try {
    const data = await getJSON(`/api/matches/${encodeURIComponent(match.id)}/streams`);
    if (request !== selectionRequest) return;
    sources = data.streams;
    sourceIndex = Math.max(0, sources.findIndex(source => source.url === previousSource));
    $('source-select').replaceChildren();
    sources.forEach((source, i) => {
      const option = element('option', '', source.label);
      option.value = String(i);
      $('source-select').append(option);
    });
    $('reload-player').disabled = false;
    if (!sources.length) {
      clearPlayer('No source available yet.');
      $('source-select').append(element('option', '', 'No sources available'));
      $('player-status').textContent = data.warnings.length ? data.warnings.join(' · ')
        : 'Sources may appear closer to kickoff. Retry shortly or open the provider page.';
      return;
    }
    $('source-select').disabled = false;
    $('next-source').disabled = sources.length < 2;
    playSource();
    if (data.warnings.length) $('player-status').textContent += ` Some sources failed: ${data.warnings.join(' · ')}`;
  } catch (error) {
    if (request !== selectionRequest) return;
    clearPlayer('Sources could not be loaded.');
    $('source-select').replaceChildren(element('option', '', 'Sources unavailable'));
    $('player-status').textContent = error.message;
    $('reload-player').disabled = false;
  }
}

async function playSource() {
  const source = sources[sourceIndex];
  if (!source) return;
  clearPlayer('Finding the direct video…');
  const request = playbackRequest;
  $('source-select').value = String(sourceIndex);
  $('stop-player').disabled = false;
  $('watch-source').textContent = `Selected source · ${source.label}`;
  $('watch-source').hidden = false;
  const previous = resolvingVideo;
  let release;
  const current = new Promise(resolve => { release = resolve; });
  resolvingVideo = current;
  let countdown = null;
  $('player-status').textContent = previous
    ? 'Waiting for the previous source check to finish…'
    : 'Resolving video without loading the provider’s player…';
  try {
    // Let an in-flight server discovery finish, then resolve only the latest selection.
    // Switching sources rapidly must not send competing discovery requests.
    if (previous) await previous;
    if (request !== playbackRequest) return;
    const deadline = performance.now() + 20000;
    const updateCountdown = () => {
      if (request !== playbackRequest) return;
      const seconds = Math.max(0, Math.ceil((deadline - performance.now()) / 1000));
      $('player-status').textContent = `Finding direct video · ${seconds} second${seconds === 1 ? '' : 's'} left…`;
    };
    updateCountdown();
    countdown = setInterval(updateCountdown, 250);
    const response = await fetch(`/api/matches/${encodeURIComponent(selected.id)}/play/${encodeURIComponent(source.id)}`, {
      method: 'POST', headers: {'X-Matchday-Request': '1'}, signal: AbortSignal.timeout(20000),
    });
    const data = await response.json();
    if (request !== playbackRequest) return;
    if (!response.ok) throw new Error(data.detail || 'Direct playback unavailable');
    directPlayer.start(data.url);
  } catch (error) {
    if (request !== playbackRequest) return;
    const message = error.name === 'TimeoutError'
      ? 'Video did not become available within 20 seconds. Try another source.'
      : error.message || 'Direct playback unavailable for this source.';
    clearPlayer(message);
    $('player-status').textContent = message;
  } finally {
    clearInterval(countdown);
    release();
    if (resolvingVideo === current) resolvingVideo = null;
  }
}

$('arsenal').addEventListener('click', () => setSport('arsenal'));
$('football').addEventListener('click', () => setSport('football'));
$('nba').addEventListener('click', () => setSport('nba'));
$('search').addEventListener('input', renderMatches);
$('provider').addEventListener('change', renderMatches);
$('refresh').addEventListener('click', loadMatches);
$('source-select').addEventListener('change', () => {sourceIndex = Number($('source-select').value); playSource();});
$('next-source').addEventListener('click', () => {sourceIndex = (sourceIndex + 1) % sources.length; playSource();});
$('reload-player').addEventListener('click', () => {if (selected) selectMatch(selected);});
$('stop-player').addEventListener('click', () => {clearPlayer('Playback stopped.'); $('player-status').textContent = 'Select a source or reload to start again.';});
loadMatches();
