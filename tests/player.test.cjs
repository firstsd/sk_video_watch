const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

class Video extends EventTarget {
  constructor() {
    super();
    this.currentTime = 42;
    this.readyState = 4;
    this.paused = false;
    this.buffered = {length: 0};
  }
  setAttribute() {}
  removeAttribute() {}
  load() {}
  remove() {}
  pause() { this.paused = true; }
  play() { this.paused = false; return Promise.resolve(); }
}

class Hls {
  static Events = {MEDIA_ATTACHED: 'attached', MANIFEST_PARSED: 'manifest', FRAG_LOADED: 'fragment', ERROR: 'error'};
  static ErrorTypes = {NETWORK_ERROR: 'networkError', MEDIA_ERROR: 'mediaError'};
  static isSupported() { return true; }
  constructor(options) { this.options = options; this.events = {}; this.loads = []; this.starts = []; }
  on(event, fn) { (this.events[event] ||= []).push(fn); }
  once(event, fn) {
    this.on(event, (...args) => {
      this.events[event] = this.events[event].filter(item => item !== once);
      fn(...args);
    });
    const once = this.events[event].at(-1);
  }
  emit(event, data) { for (const fn of [...(this.events[event] || [])]) fn(event, data); }
  attachMedia(video) { this.video = video; this.emit(Hls.Events.MEDIA_ATTACHED); }
  loadSource(url) { this.loads.push(url); }
  startLoad(position) { this.starts.push(position); }
  recoverMediaError() { this.attachMedia(this.video); }
  stopLoad() {}
  destroy() {}
}

function setup() {
  const nodes = new Map();
  const document = {
    createElement: () => new Video(),
    getElementById(id) {
      if (!nodes.has(id)) nodes.set(id, {textContent: '', dataset: {}, replaceChildren() {}});
      return nodes.get(id);
    },
  };
  const context = vm.createContext({document, window: {Hls}, Hls, performance, setInterval: () => 1, clearInterval() {}});
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../app/static/player.js'), 'utf8') + '\nthis.Player = DirectPlayer;', context);
  return {player: new context.Player(), nodes};
}

test('media recovery preserves the existing source and does not prematurely pause the video', () => {
  const {player, nodes} = setup();
  player.start('/media/playlist');
  const hls = player.hls;
  hls.firstLevel = 1;
  hls.emit(Hls.Events.MANIFEST_PARSED);
  assert.equal(hls.loadLevel, undefined);
  assert.equal(hls.options.startLevel, -1);
  assert.equal(hls.options.capLevelToPlayerSize, true);
  assert.equal(hls.options.maxBufferLength, 60);
  assert.equal(hls.options.liveSyncDurationCount, 5);
  player.video.dispatchEvent(new Event('error'));
  assert.equal(player.video.paused, false);
  hls.emit(Hls.Events.ERROR, {type: Hls.ErrorTypes.MEDIA_ERROR, details: 'bufferAppendError', fatal: true});
  assert.deepEqual(hls.loads, ['/media/playlist']);
  player.video.dispatchEvent(new Event('playing'));
  assert.notEqual(nodes.get('video-state').textContent, 'Error');
  hls.emit(Hls.Events.ERROR, {type: Hls.ErrorTypes.NETWORK_ERROR, details: 'fragLoadError', fatal: true});
  assert.deepEqual(hls.starts, [42]);
  player.stop();
});

test('rapid source switching waits for the active check and skips superseded selections', async () => {
  const requests = [], starts = [], nodes = new Map();
  const node = () => ({append() {}, replaceChildren() {}, addEventListener() {}, setAttribute() {}});
  const document = {
    createElement: node,
    getElementById(id) { if (!nodes.has(id)) nodes.set(id, node()); return nodes.get(id); },
  };
  const context = vm.createContext({
    document, AbortSignal, performance, setInterval, clearInterval,
    DirectPlayer: class { stop() {} start(url) { starts.push(url); } },
    fetch(url, options) { return new Promise(resolve => requests.push({url, resolve, options})); },
  });
  const source = fs.readFileSync(path.join(__dirname, '../app/static/app.js'), 'utf8');
  vm.runInContext(source.replace(/\nloadMatches\(\);\s*$/, '\n'), context);
  vm.runInContext("selected={id:'match'}; sources=[{id:'a',label:'A'},{id:'b',label:'B'},{id:'c',label:'C'}]", context);
  const a = vm.runInContext('playSource()', context);
  const b = vm.runInContext('sourceIndex=1; playSource()', context);
  const c = vm.runInContext('sourceIndex=2; playSource()', context);
  assert.equal(requests.length, 1);
  assert.equal(requests[0].options.headers['X-Matchday-Request'], '1');
  assert.match(nodes.get('player-status').textContent, /previous source check/);
  requests[0].resolve({ok: true, json: async () => ({url: '/video/a'})});
  await new Promise(setImmediate);
  assert.deepEqual(requests.map(r => r.url), ['/api/matches/match/play/a', '/api/matches/match/play/c']);
  assert.deepEqual(starts, []);
  requests[1].resolve({ok: true, json: async () => ({url: '/video/c'})});
  await Promise.all([a, b, c]);
  assert.deepEqual(starts, ['/video/c']);
});

test('buffer health shows risk only during playback and returns to neutral when paused', () => {
  const {player, nodes} = setup();
  player.start('/media/playlist');
  const video = player.video;
  video.buffered = {length: 1, start: () => 40, end: () => 43};
  video.dispatchEvent(new Event('playing'));
  assert.equal(nodes.get('video-buffer').dataset.tone, 'bad');
  assert.match(nodes.get('video-buffer').dataset.label, /buffering risk/);
  video.buffered.end = () => 50;
  video.dispatchEvent(new Event('playing'));
  assert.equal(nodes.get('video-buffer').dataset.tone, 'good');
  video.pause();
  video.dispatchEvent(new Event('pause'));
  assert.equal(nodes.get('video-buffer').dataset.tone, 'neutral');
  player.stop();
  assert.equal(nodes.get('video-buffer').textContent, '—');
  assert.equal(nodes.get('video-buffer').dataset.tone, 'neutral');
});

test('source countdown uses elapsed time and clears its timer on timeout', async () => {
  const nodes = new Map(), timers = new Map();
  let now = 0, rejectRequest;
  const node = () => ({append() {}, replaceChildren() {}, addEventListener() {}, setAttribute() {}});
  const context = vm.createContext({
    document: {createElement: node, getElementById(id) { if (!nodes.has(id)) nodes.set(id, node()); return nodes.get(id); }},
    AbortSignal, performance: {now: () => now},
    setInterval(fn) { timers.set(1, fn); return 1; },
    clearInterval(id) { timers.delete(id); },
    DirectPlayer: class { stop() {} start() {} },
    fetch() { return new Promise((resolve, reject) => { rejectRequest = reject; }); },
  });
  const source = fs.readFileSync(path.join(__dirname, '../app/static/app.js'), 'utf8');
  vm.runInContext(source.replace(/\nloadMatches\(\);\s*$/, '\n'), context);
  vm.runInContext("selected={id:'match'}; sources=[{id:'a',label:'A'}]", context);
  const pending = vm.runInContext('playSource()', context);
  assert.match(nodes.get('player-status').textContent, /20 seconds left/);
  now = 5100;
  timers.get(1)();
  assert.match(nodes.get('player-status').textContent, /15 seconds left/);
  now = 20000;
  timers.get(1)();
  assert.match(nodes.get('player-status').textContent, /0 seconds left/);
  rejectRequest({name: 'TimeoutError'});
  await pending;
  assert.match(nodes.get('player-status').textContent, /within 20 seconds/);
  assert.equal(timers.size, 0);
});
