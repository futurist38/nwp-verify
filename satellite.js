/* GK2A viewer. Only metadata lives on Pages; every image is requested from KMA.
   No API key, image proxy, service worker, or persistent image store. */
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (typeof document !== 'undefined') api.mount(document);
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';
  const MINUTE = 60000, CADENCE = 2 * MINUTE;
  const ORIGIN = 'https://www.weather.go.kr';
  const PREFIX = ORIGIN + '/w/repositary/image/sat/gk2a/KO/gk2a_ami_le1b_';
  const CHANNELS = {
    'rgb-cs': { label: 'RGB 구름강조', file: 'rgb-cs_ko005lc_', suffix: '.thn.jpg' },
    'rgb-s-daynight': { label: 'RGB 주야간합성', file: 'rgb-s-daynight_ko020lc_', suffix: '.png' },
    'ir105': { label: '적외 10.5 μm', file: 'ir105_ko020lc_', suffix: '.thn.png' }
  };
  const utcStamp = time => new Date(time).toISOString().replace(/\D/g, '').slice(0, 12);
  function imageURL(channel, time) {
    if (!Object.hasOwn(CHANNELS, channel) || !Number.isFinite(time) || time % CADENCE) throw new Error('Invalid satellite frame');
    const c = CHANNELS[channel];
    return PREFIX + c.file + utcStamp(time) + c.suffix;
  }
  function kst(time, date = true) {
    const s = new Date(time + 9 * 60 * MINUTE).toISOString();
    return (date ? s.slice(0, 10).replace(/-/g, '.') + ' ' : '') + s.slice(11, 16);
  }
  function timeline(latest, hours, step) {
    if (!Number.isFinite(latest) || ![1, 3, 6].includes(hours) || ![2, 10].includes(step)) return [];
    const count = hours * 60 / step;
    return Array.from({length: count + 1}, (_, i) => latest - (count - i) * step * MINUTE);
  }
  function latestCandidates(now, known) {
    // KMA publishes after acquisition. First try a four-minute publication lag,
    // then a bounded fallback window. Successful frames are probed forward below.
    const start = Math.floor(now / CADENCE) * CADENCE - 2 * CADENCE;
    return Array.from({length: 5}, (_, i) => start - i * CADENCE).filter(t => !known || t > known);
  }
  function catalogFrames(catalog, channel, now) {
    const rows = catalog && catalog.channels && catalog.channels[channel] && catalog.channels[channel].frames;
    if (!Array.isArray(rows)) return [];
    const times = new Set();
    for (const frame of rows) {
      const time = Date.parse(frame.time);
      if (!Number.isFinite(time) || time % CADENCE || time > now || time < now - 6 * 60 * MINUTE) continue;
      if (frame.url === imageURL(channel, time)) times.add(time);
    }
    return [...times].sort((a,b) => a-b);
  }
  function loadImage(url) {
    return new Promise((resolve, reject) => {
      const img = new Image();
      img.decoding = 'async';
      img.referrerPolicy = 'strict-origin-when-cross-origin';
      let finished = false;
      const finish = (error) => {
        if (finished) return;
        finished = true; clearTimeout(timer); img.onload = img.onerror = null;
        if (error) { img.src = ''; reject(error); } else resolve(img);
      };
      const timer = setTimeout(() => finish(new Error('timeout')), 18000);
      img.onload = () => finish(img.naturalWidth ? null : new Error('empty image'));
      img.onerror = () => finish(new Error('unavailable'));
      img.src = url;
    });
  }
  class ImageCache {
    constructor(limit = 6, loader = loadImage) { this.limit = limit; this.loader = loader; this.entries = new Map(); }
    get(url) {
      if (this.entries.has(url)) {
        const p = this.entries.get(url); this.entries.delete(url); this.entries.set(url,p); return p;
      }
      const p = Promise.resolve().then(() => this.loader(url)).catch(error => {
        if (this.entries.get(url) === p) this.entries.delete(url);
        throw error;
      });
      this.entries.set(url,p);
      while (this.entries.size > this.limit) this.entries.delete(this.entries.keys().next().value);
      return p;
    }
  }
  function mount(doc) {
    const section = doc.getElementById('obsSatellite');
    if (!section) return;
    const $ = id => doc.getElementById(id);
    const cache = new ImageCache(6);
    let channel = 'rgb-cs', latest = null, frames = [], index = 0, catalog = null;
    let viewVersion = 0, refreshVersion = 0, playing = false, playTimer = null;
    let followLatest = true, started = false, displayed = null, refreshInFlight = false;
    const confirmedLatest = {};
    const active = () => !section.hidden && $('tab-obs').classList.contains('on') && !doc.hidden;
    function status(message, error = false) {
      $('satelliteStatus').textContent = message;
      $('satelliteStatus').classList.toggle('error',error);
    }
    function stop() {
      playing = false; clearTimeout(playTimer); playTimer = null;
      $('satellitePlay').textContent = '▶ 재생'; $('satellitePlay').setAttribute('aria-pressed','false');
    }
    function age() {
      const span = $('satelliteAge');
      if (displayed === null) {span.textContent='';span.classList.remove('stale');return;}
      const minutes = Math.max(0, Math.floor((Date.now() - displayed) / MINUTE));
      span.textContent = minutes + '분 전 관측' + (minutes > 20 ? ' · 과거 영상' : '');
      span.classList.toggle('stale',minutes > 20);
    }
    function controls() {
      const range = $('satelliteSlider');
      range.max = String(Math.max(0,frames.length-1)); range.value = String(index); range.disabled = !frames.length;
      $('satellitePrev').disabled = !frames.length || index === 0;
      $('satelliteNext').disabled = !frames.length || index === frames.length-1;
      $('satellitePlay').disabled = frames.length < 2;
      const selected = frames[index];
      $('satelliteSelected').textContent = selected === undefined ? '—' : kst(selected,false) + ' KST';
      range.setAttribute('aria-valuetext',selected === undefined ? '영상 없음' : kst(selected) + ' KST');
      $('satelliteTicks').replaceChildren();
      if (frames.length) [frames[0],frames[Math.floor((frames.length-1)/2)],frames.at(-1)].forEach(t => {
        const label = doc.createElement('span');label.textContent=kst(t).slice(5);$('satelliteTicks').append(label);
      });
    }
    function rebuild(selected) {
      frames = timeline(latest,Number($('satelliteHours').value),Number($('satelliteStep').value));
      index = followLatest ? frames.length-1 : Math.max(0,frames.findIndex(t => t >= selected));
      controls();
    }
    function prefetch() {
      // Two neighbours only. Six compressed/decoded frame references at most;
      // switching away from this tab stops further preloading and polling.
      if (!active()) return;
      for (const i of [index+1,index+2]) if (frames[i] !== undefined) cache.get(imageURL(channel,frames[i])).catch(() => {});
    }
    async function show(time, announce = true) {
      if (!Number.isFinite(time)) return false;
      const version = ++viewVersion, requestedChannel = channel;
      $('satelliteViewport').setAttribute('aria-busy','true');
      $('satelliteImage').hidden = true; $('satelliteEmpty').hidden = false;
      $('satelliteEmpty').textContent = kst(time) + ' KST 영상을 불러오는 중…';
      $('satelliteTimestamp').textContent = '요청 시각: ' + kst(time) + ' KST';
      displayed = null; age();
      if (announce) status('영상을 불러오고 있습니다.');
      try {
        const loaded = await cache.get(imageURL(requestedChannel,time));
        if (version !== viewVersion || channel !== requestedChannel || !active()) return false;
        const image = $('satelliteImage');image.src = loaded.src;
        image.alt = '천리안 2A호 한반도 '+CHANNELS[channel].label+' · '+kst(time)+' KST';
        image.hidden=false;$('satelliteEmpty').hidden=true;
        $('satelliteTimestamp').textContent = kst(time)+' KST · '+CHANNELS[channel].label;
        displayed = time;age();
        confirmedLatest[channel] = Math.max(confirmedLatest[channel] ?? 0,time);
        if (announce) status(followLatest ? '최신 영상 보기 · 2분마다 갱신 확인' : '선택한 시각의 영상');
        prefetch(); return true;
      } catch (error) {
        if (version !== viewVersion || channel !== requestedChannel || !active()) return false;
        stop();$('satelliteEmpty').textContent='이 시각의 영상이 없거나 원본에 연결할 수 없습니다.';
        status('다른 시각을 선택하거나 최신 영상 확인을 눌러주세요.',true);
        return false;
      } finally {
        if (version === viewVersion) $('satelliteViewport').setAttribute('aria-busy','false');
      }
    }
    async function refresh() {
      if (!active() || refreshInFlight || !followLatest || playing) return;
      refreshInFlight=true;
      const version = ++refreshVersion, requestedChannel = channel;
      const valid = () => version === refreshVersion && channel === requestedChannel && active() && followLatest;
      status('최신 관측 영상을 확인하고 있습니다…');
      try {
        let found = confirmedLatest[channel] ?? null, searched = false;
        const deadline = Date.now()+35000;
        for (const time of latestCandidates(Date.now(),found)) {
          if (!valid()) return;
          if (Date.now()>deadline) break;
          searched=true;
          try {await cache.get(imageURL(requestedChannel,time));found=time;break;} catch (_) { /* missing acquisition */ }
        }
        if (!valid()) return;
        if (found !== null) {
          // Seek newer acquisitions up to two minutes before now. Stop at the first missing frame.
          const ceiling = Math.floor(Date.now()/CADENCE)*CADENCE-CADENCE;
          const forwardLimit = Math.min(ceiling,found+2*CADENCE);
          for (let time=found+CADENCE;time<=forwardLimit;time+=CADENCE) {
            if (!valid() || Date.now()>deadline) break;
            try {await cache.get(imageURL(requestedChannel,time));found=time;} catch (_) {break;}
          }
          if (!valid()) return;
          latest=found;rebuild(found);await show(found);
          if (valid() && Date.now()-found>20*MINUTE) status('새 영상을 확인하지 못해 마지막 확인 시각을 표시합니다.',true);
        } else if (searched) {
          $('satelliteEmpty').hidden=false;$('satelliteEmpty').textContent='최신 영상을 확인하지 못했습니다.';
          $('satelliteTimestamp').textContent='관측시각 확인 불가';
          status('원본 연결 또는 자료 제공 상태를 확인한 뒤 다시 시도해주세요.',true);
        }
      } finally {if(version===refreshVersion)refreshInFlight=false;}
    }
    function cancelWork() {stop();viewVersion++;refreshVersion++;refreshInFlight=false;$('satelliteViewport').setAttribute('aria-busy','false');}
    async function activate() {
      if (!active()) return;
      if (!started) {
        started=true;
        try {
          const controller = new AbortController();const timer=setTimeout(()=>controller.abort(),5000);
          try {const response=await fetch('satellite.json',{cache:'no-cache',signal:controller.signal});if(response.ok)catalog=await response.json();}
          finally {clearTimeout(timer);}
        } catch (_) { /* validated public URL templates can work without the metadata seed */ }
        if (!active()) return;
        for(const key of Object.keys(CHANNELS)) {
          const known = catalogFrames(catalog,key,Date.now());
          if(known.length) confirmedLatest[key] = known.at(-1);
        }
        latest=confirmedLatest[channel] ?? null;
        if (latest !== null) {rebuild(latest);show(latest);}
        refresh();
      } else if (frames.length) {
        await show(frames[index]);if(followLatest)refresh();
      } else refresh();
    }
    function subtab(satellite) {
      cancelWork();
      $('obsGround').hidden=satellite;section.hidden=!satellite;
      $('obsGroundTab').setAttribute('aria-selected',String(!satellite));$('obsSatelliteTab').setAttribute('aria-selected',String(satellite));
      if(satellite)activate();
    }
    $('obsGroundTab').addEventListener('click',()=>subtab(false));
    $('obsSatelliteTab').addEventListener('click',()=>subtab(true));
    $('obsSections').addEventListener('keydown',event=>{
      if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;
      event.preventDefault();event.stopPropagation();
      const button=$(['ArrowLeft','Home'].includes(event.key)?'obsGroundTab':'obsSatelliteTab');button.click();button.focus();
    });
    doc.querySelectorAll('#tabs button').forEach(button=>button.addEventListener('click',()=>{
      cancelWork();if(button.dataset.tab==='obs' && !section.hidden)activate();
    }));
    doc.querySelectorAll('[data-satellite-channel]').forEach(button=>button.addEventListener('click',()=>{
      if(button.dataset.satelliteChannel===channel)return;
      const selected=frames[index];cancelWork();channel=button.dataset.satelliteChannel;
      doc.querySelectorAll('[data-satellite-channel]').forEach(b=>b.setAttribute('aria-pressed',String(b===button)));
      $('satelliteChannelNote').hidden=channel!=='rgb-s-daynight';
      const known=catalogFrames(catalog,channel,Date.now());
      latest=Math.max(known.at(-1) ?? 0,latest ?? 0) || null;
      if(latest!==null) {rebuild(selected);show(frames[index]);}
      if(followLatest)refresh();
    }));
    function select(i) {cancelWork();followLatest=false;index=Math.max(0,Math.min(frames.length-1,i));controls();show(frames[index]);}
    $('satellitePrev').addEventListener('click',()=>select(index-1));
    $('satelliteNext').addEventListener('click',()=>select(index+1));
    $('satelliteSlider').addEventListener('input',()=>select(Number($('satelliteSlider').value)));
    for(const id of ['satelliteHours','satelliteStep']) $(id).addEventListener('change',()=>{
      const selected=frames[index];cancelWork();rebuild(selected);show(frames[index]);
    });
    for(const id of ['satelliteRefresh','satelliteLatest']) $(id).addEventListener('click',()=>{
      cancelWork();followLatest=true;if(latest!==null){rebuild(latest);show(latest);}refresh();
    });
    $('satellitePlay').addEventListener('click',()=>{
      if(playing){stop();status('재생을 멈췄습니다.');return;}
      cancelWork();followLatest=false;playing=true;
      $('satellitePlay').textContent='❚❚ 정지';$('satellitePlay').setAttribute('aria-pressed','true');
      const tick=async()=>{
        if(!playing||!active())return;
        index=index>=frames.length-1?0:index+1;controls();
        const ok=await show(frames[index],false);
        if(!playing||!ok)return;
        status('재생 중 · '+(index+1)+' / '+frames.length);
        if(index===frames.length-1){stop();status('재생 완료');return;}
        playTimer=setTimeout(tick,Number($('satelliteSpeed').value));
      };
      tick();
    });
    doc.addEventListener('visibilitychange',()=>{if(doc.hidden)cancelWork();else if(active())activate();});
    setInterval(()=>{if(active()){age();refresh();}},2*MINUTE);
    const params=new URLSearchParams(location.search);
    if(params.get('tab')==='obs'&&params.get('view')==='satellite')subtab(true);
  }
  return {CHANNELS,imageURL,kst,timeline,latestCandidates,catalogFrames,ImageCache,mount};
});
