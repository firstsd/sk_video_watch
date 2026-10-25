/* Native video + locally hosted hls.js. No provider HTML, frames, or scripts. */
class DirectPlayer {
  constructor() {
    this.video = null;
    this.hls = null;
    this.timer = null;
  }

  text(id, value) { document.getElementById(id).textContent = value; }

  health(id, value, tone = 'neutral', label = '') {
    const node = document.getElementById(id);
    node.textContent = value;
    node.dataset.tone = tone;
    node.dataset.label = label;
  }

  stop() {
    clearInterval(this.timer);
    this.timer = null;
    if (this.hls) this.hls.destroy();
    this.hls = null;
    if (this.video) {
      this.video.pause();
      this.video.removeAttribute('src');
      this.video.load();
      this.video.remove();
    }
    this.video = null;
    for (const id of ['video-buffer', 'video-delay', 'video-segment', 'video-stalls', 'video-dropped', 'video-errors']) this.health(id, '—');
    this.health('video-state', 'Stopped');
    this.text('health-summary', 'Waiting for playback measurements.');
  }

  start(url) {
    this.stop();
    const video = document.createElement('video');
    this.video = video;
    video.controls = true;
    video.playsInline = true;
    video.autoplay = true;
    video.setAttribute('aria-label', 'Match video');
    document.getElementById('screen').replaceChildren(video);
    this.text('video-state', 'Loading');
    this.text('player-status', 'Loading direct video. Press play if your browser pauses autoplay.');
    let started = false, stalls = 0, stalledAt = null, stalledMs = 0, stallMediaTime = 0;
    let lastTime = 0, lastProgress = performance.now(), errors = 0;
    let networkRecovery = 0, mediaRecovery = 0, failed = false;
    let lastChunk = null, errorTimes = [], frameSamples = [];
    const finishStall = () => {
      if (stalledAt !== null) stalledMs += performance.now() - stalledAt;
      stalledAt = null;
    };
    const markStall = () => {
      if (started && !failed && !video.paused && !video.seeking && stalledAt === null) {
        stalls++;
        stalledAt = performance.now();
        stallMediaTime = video.currentTime;
      }
    };
    const fail = (message) => {
      failed = true;
      finishStall();
      video.pause();
      this.text('video-state', 'Error');
      this.text('player-status', message);
    };
    const update = () => {
      if (this.video !== video) return;
      let ahead = 0;
      for (let i = 0; i < video.buffered.length; i++) {
        if (video.currentTime >= video.buffered.start(i) && video.currentTime <= video.buffered.end(i)) {
          ahead = video.buffered.end(i) - video.currentTime;
          break;
        }
      }
      if (video.currentTime > lastTime + 0.01) {
        if (video.readyState >= 2 && !video.paused) started = true;
        lastProgress = performance.now();
        if (stalledAt !== null && video.readyState >= 3 && video.currentTime > stallMediaTime + 0.05) finishStall();
      } else if (!document.hidden && performance.now() - lastProgress > 2000) markStall();
      lastTime = video.currentTime;
      const active = started && !video.paused && !video.seeking && !video.ended && !failed;
      const bufferTone = !active ? 'neutral' : ahead < 2 ? 'bad' : ahead < 5 ? 'warn' : 'good';
      this.health('video-buffer', started || video.readyState ? `${ahead.toFixed(1)} s` : '—', bufferTone,
        !active ? 'Video ready to play' : ahead < 2 ? 'Low · buffering risk' : ahead < 5 ? 'Watch · little reserve' : 'Good · healthy reserve');
      const details = this.hls?.latestLevelDetails;
      const latency = this.hls?.latency;
      this.health('video-delay', details?.live && started && Number.isFinite(latency) ? `${Math.max(0, latency).toFixed(1)} s` : '—', 'neutral', 'Behind the provider, not the stadium');
      const duration = stalledMs + (stalledAt === null ? 0 : performance.now() - stalledAt);
      this.health('video-stalls', `${stalls} / ${(duration / 1000).toFixed(1)} s`, !started ? 'neutral' : stalledAt !== null ? 'bad' : 'good', stalledAt !== null ? 'Buffering now' : `${stalls ? 'Recovered · ' : ''}Count / total time`);
      const quality = video.getVideoPlaybackQuality?.();
      const now = performance.now();
      if (quality && active) {
        frameSamples.push({at: now, dropped: quality.droppedVideoFrames, total: quality.totalVideoFrames});
        frameSamples = frameSamples.filter(sample => now - sample.at <= 10000);
      } else frameSamples = [];
      const first = frameSamples[0];
      const frames = first ? quality.totalVideoFrames - first.total : 0;
      const dropRate = frames > 0 ? Math.max(0, quality.droppedVideoFrames - first.dropped) / frames : null;
      this.health('video-dropped', quality && started ? `${quality.droppedVideoFrames} / ${quality.totalVideoFrames}` : '—', dropRate === null ? 'neutral' : dropRate > .05 ? 'bad' : dropRate > .01 ? 'warn' : 'good', dropRate === null ? 'Dropped / total · measuring' : `${(dropRate * 100).toFixed(1)}% dropped recently`);
      errorTimes = errorTimes.filter(at => now - at < 30000);
      this.health('video-errors', String(errors), !started ? 'neutral' : errorTimes.length >= 3 ? 'bad' : errorTimes.length ? 'warn' : 'good', `${errorTimes.length} in the last 30 seconds`);
      if (lastChunk) {
        const ratio = lastChunk.ms / (lastChunk.seconds * 1000);
        const recent = active && Number.isFinite(ratio) && lastChunk.seconds > 0 && now - lastChunk.at < Math.max(15000, lastChunk.seconds * 3000);
        this.health('video-segment', `${Math.round(lastChunk.ms)} ms`, !recent ? 'neutral' : ratio >= 1 ? 'bad' : ratio >= .5 ? 'warn' : 'good', !recent ? 'Last sample · not current' : ratio >= 1 ? 'Slow · cannot keep up' : ratio >= .5 ? 'Watch · download slowing' : 'Good · faster than playback');
      }
      const state = failed ? 'Error' : video.ended ? 'Ended' : video.seeking ? 'Seeking' : video.paused ? 'Paused' : stalledAt !== null ? 'Buffering' : started ? 'Playing' : 'Loading';
      this.health('video-state', state, failed || stalledAt !== null ? 'bad' : active ? bufferTone : 'neutral');
      this.text('health-summary', failed ? 'Playback failed. Reload or try another source.' : !active ? `${state}. Health colors resume when video is playing.` : stalledAt !== null ? 'Buffering now: the player is waiting for more video.' : ahead < 2 ? 'Buffer running low: playback may pause if video delivery does not catch up.' : ahead < 5 ? 'Small buffer: keep an eye on video delivery.' : errorTimes.length ? 'Video has a healthy buffer, but recent requests needed attention.' : 'Healthy buffer: there is video ready to keep playback moving.');
    };
    video.addEventListener('waiting', markStall);
    video.addEventListener('playing', () => {
      failed = false;
      finishStall();
      lastProgress = performance.now();
      this.text('player-status', 'Playing direct video. Video health updates every second.');
      update();
    });
    video.addEventListener('pause', () => { finishStall(); update(); });
    video.addEventListener('seeking', () => { finishStall(); });
    video.addEventListener('seeked', () => { lastProgress = performance.now(); lastTime = video.currentTime; });
    video.addEventListener('error', () => {
      // hls.js handles MediaSource errors and may recover by reattaching the video.
      if (!this.hls) fail('The video could not be decoded or loaded. Try another source.');
    });
    const attemptPlay = () => video.play().catch(() => {
      if (this.video === video) this.text('player-status', 'Video ready. Press play to start.');
    });
    if (window.Hls?.isSupported()) {
      const hls = new Hls({
        enableWorker: true,
        startLevel: -1,
        capLevelToPlayerSize: true,
        maxBufferLength: 60,
        maxMaxBufferLength: 120,
        backBufferLength: 30,
        liveSyncDurationCount: 5,
        liveMaxLatencyDurationCount: 10,
      });
      this.hls = hls;
      // Recovery also attaches media; reloading here would discard its resume position.
      hls.once(Hls.Events.MEDIA_ATTACHED, () => hls.loadSource(url));
      hls.on(Hls.Events.MANIFEST_PARSED, () => {
        attemptPlay();
      });
      hls.on(Hls.Events.FRAG_LOADED, (_, data) => {
        if (data.frag.type !== 'main' || data.frag.sn === 'initSegment') return;
        const stats = data.part?.stats || data.frag.stats;
        const duration = stats.loading.end - stats.loading.start;
        if (Number.isFinite(duration) && duration > 0) {
          lastChunk = {ms: duration, seconds: data.part?.duration || data.frag.duration, at: performance.now()};
        }
      });
      hls.on(Hls.Events.ERROR, (_, data) => {
        if (data.type === Hls.ErrorTypes.NETWORK_ERROR) { errors++; errorTimes.push(performance.now()); }
        if (!data.fatal) return;
        const code = Number(data.response?.code);
        const detail = `${data.details || data.type}${code > 0 ? `, HTTP ${code}` : ''}`;
        if (data.type === Hls.ErrorTypes.NETWORK_ERROR && networkRecovery++ < 2) {
          this.text('player-status', `Video request failed (${detail}). Retrying…`);
          hls.startLoad(video.currentTime || -1);
        } else if (data.type === Hls.ErrorTypes.MEDIA_ERROR && mediaRecovery++ < 1) {
          this.text('player-status', `Recovering video playback (${detail})…`);
          hls.recoverMediaError();
        } else {
          hls.stopLoad();
          fail(`Video delivery failed (${detail}). Reload for a fresh stream or try another source.`);
        }
        update();
      });
      hls.attachMedia(video);
    } else if (video.canPlayType('application/vnd.apple.mpegurl')) {
      video.src = url;
      video.addEventListener('loadedmetadata', attemptPlay, {once: true});
      this.text('video-segment', 'Not exposed');
    } else {
      fail('This browser does not support HLS video. Please use a current Chrome or Safari.');
    }
    // Only playback events and media requests feed these numbers; no website probes.
    this.timer = setInterval(update, 1000);
    update();
  }
}
