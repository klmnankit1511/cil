/* ============================================================
   CIL Prep — MCQ practice app
   Vanilla JS, hash routing, localStorage for progress + bookmarks.
   ============================================================ */

(() => {
  'use strict';

  /* ---------------------------------------------------------- data */

  const PRETTY = {
    Dataabase: 'Database',
    Informationsystem: 'Information Systems',
    TOC: 'Theory of Computation',
    Programming_and_Data_structure: 'Programming & Data Structures',
    REASONING_PRACTISE_BOOK: 'SSC Solved Papers',
    Compiler_design: 'Compiler Design',
    Computer_Network: 'Computer Networks',
    Computer_Organization: 'Computer Organization',
    Operating_system: 'Operating Systems',
    Quantitative_Aptitude: 'Quantitative Aptitude',
    Software_engineering: 'Software Engineering',
    Verbal_Ability: 'Verbal Ability',
    Digital_Logic: 'Digital Logic',
  };

  const RAW = (window.MCQ_DATA && window.MCQ_DATA.subjects) || [];
  const SUBJECTS = RAW.map((s, i) => ({
    id: s.file,
    idx: i,
    name: PRETTY[s.file] || s.name || s.file.replace(/_/g, ' '),
    questions: s.questions,
    total: s.questions.length,
    keyed: s.questions.filter((q) => q.a >= 0).length,
    explained: s.questions.filter((q) => q.e).length,
  })).sort((a, b) => b.total - a.total);

  const BY_ID = Object.fromEntries(SUBJECTS.map((s) => [s.id, s]));
  const TOTALS = SUBJECTS.reduce(
    (a, s) => ({
      total: a.total + s.total,
      keyed: a.keyed + s.keyed,
      explained: a.explained + s.explained,
    }),
    { total: 0, keyed: 0, explained: 0 }
  );

  /* ---------------------------------------------------------- storage */

  const store = {
    get(key, fallback) {
      try { return JSON.parse(localStorage.getItem('cil.' + key)) ?? fallback; }
      catch { return fallback; }
    },
    set(key, val) {
      try { localStorage.setItem('cil.' + key, JSON.stringify(val)); } catch { /* full */ }
    },
  };

  let bookmarks = new Set(store.get('bookmarks', []));
  let stats = store.get('stats', {});          // { subjectId: {seen, correct, wrong} }

  const saveBookmarks = () => store.set('bookmarks', [...bookmarks]);
  const saveStats = () => store.set('stats', stats);

  /* ---------------------------------------------------------- helpers */

  const $ = (sel, root = document) => root.querySelector(sel);
  const app = $('#app');
  const esc = (s) => String(s).replace(/[&<>"']/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const num = (n) => n.toLocaleString('en-IN');
  const pct = (a, b) => (b ? Math.round((a / b) * 100) : 0);

  const ICON = {
    check: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="m4.5 12.5 5 5 10-11"/></svg>',
    cross: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><path d="M6 6l12 12M18 6L6 18"/></svg>',
    info: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 7.6v.4"/></svg>',
    star: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linejoin="round"><path d="m12 3.6 2.6 5.5 5.9.8-4.3 4.2 1.1 6-5.3-2.9-5.3 2.9 1.1-6L3.5 9.9l5.9-.8z"/></svg>',
    starFill: '<svg viewBox="0 0 24 24" fill="currentColor" stroke="currentColor" stroke-width="1.9" stroke-linejoin="round"><path d="m12 3.6 2.6 5.5 5.9.8-4.3 4.2 1.1 6-5.3-2.9-5.3 2.9 1.1-6L3.5 9.9l5.9-.8z"/></svg>',
    search: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.1" stroke-linecap="round"><circle cx="11" cy="11" r="6.5"/><path d="m16 16 4 4"/></svg>',
    chev: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="m9 5 7 7-7 7"/></svg>',
    left: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="m15 5-7 7 7 7"/></svg>',
    shuffle: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round"><path d="M17 4h4v4M21 4l-6.5 6.5M17 20h4v-4M21 20l-7-7M3 5l5 5M3 19l16-16"/></svg>',
    empty: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="7"/><path d="m16.5 16.5 4 4"/></svg>',
  };

  let toastTimer;
  function toast(msg) {
    const el = $('#toast');
    el.textContent = msg;
    el.classList.add('show');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => el.classList.remove('show'), 1800);
  }

  /** Count a number up from 0 — purely decorative, so it respects reduced motion. */
  function countUp(el, to) {
    if (matchMedia('(prefers-reduced-motion: reduce)').matches) {
      el.textContent = num(to); return;
    }
    const dur = 900, t0 = performance.now();
    const step = (t) => {
      const k = Math.min(1, (t - t0) / dur);
      el.textContent = num(Math.round(to * (1 - Math.pow(1 - k, 3))));
      if (k < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }

  function stagger(sel, base = 40) {
    app.querySelectorAll(sel).forEach((el, i) => {
      el.style.animationDelay = Math.min(i * base, 420) + 'ms';
    });
  }

  /* ---------------------------------------------------------- theme */

  const themeBtn = $('#themeBtn');
  const applyTheme = (t) => document.documentElement.setAttribute('data-theme', t || '');
  applyTheme(store.get('theme', ''));
  themeBtn.addEventListener('click', () => {
    const cur = document.documentElement.getAttribute('data-theme');
    const isDark = cur === 'dark' ||
      (!cur && matchMedia('(prefers-color-scheme: dark)').matches);
    const next = isDark ? 'light' : 'dark';
    applyTheme(next);
    store.set('theme', next);
  });

  /* ---------------------------------------------------------- views */

  function viewHome() {
    const top = SUBJECTS.slice(0, 10);
    const max = Math.max(...top.map((s) => s.total));

    app.innerHTML = `
      <section class="view">
        <div class="hero">
          <span class="eyebrow"><i class="dot"></i> Coal India Ltd &middot; Computer Science</span>
          <h1>Practise ${num(TOTALS.total)} exam questions.</h1>
          <p class="lede">Every MCQ extracted from the course notes &mdash; questions, options,
            answer keys and worked explanations &mdash; in one place you can drill through.</p>
        </div>

        <div class="tiles">
          <div class="tile"><div class="label">Questions</div>
            <div class="value" data-count="${TOTALS.total}">0</div>
            <div class="sub">across ${SUBJECTS.length} subjects</div></div>
          <div class="tile"><div class="label">With answer key</div>
            <div class="value" data-count="${TOTALS.keyed}">0</div>
            <div class="sub">${pct(TOTALS.keyed, TOTALS.total)}% of all questions</div></div>
          <div class="tile"><div class="label">With explanation</div>
            <div class="value" data-count="${TOTALS.explained}">0</div>
            <div class="sub">worked solutions included</div></div>
          <div class="tile"><div class="label">Bookmarked</div>
            <div class="value" data-count="${bookmarks.size}">0</div>
            <div class="sub">saved for review</div></div>
        </div>

        <div class="section-head">
          <h2>Question bank by subject</h2>
          <p class="spacer">largest first</p>
        </div>
        <div class="chart">
          ${top.map((s, i) => `
            <div class="bar-row">
              <div class="name" title="${esc(s.name)}">${esc(s.name)}</div>
              <div class="bar-track">
                <div class="bar" style="width:${(s.total / max) * 100}%;animation-delay:${i * 55}ms"></div>
                <span class="bar-val">${num(s.total)}</span>
              </div>
            </div>`).join('')}
        </div>

        <div class="section-head">
          <h2>Choose a subject</h2>
          <p class="spacer">tap to start practising</p>
        </div>
        <div class="grid-subjects">
          ${SUBJECTS.map((s) => {
            const st = stats[s.id] || {};
            const done = st.seen || 0;
            return `
            <button class="subject-card" data-go="#/practice/${encodeURIComponent(s.id)}">
              <div class="row">
                <h3>${esc(s.name)}</h3>
                <span class="chev">${ICON.chev}</span>
              </div>
              <div class="meter"><i style="width:${pct(done, s.total)}%"></i></div>
              <div class="meter-legend">
                <span>${num(s.total)} questions</span>
                <span>${done ? pct(done, s.total) + '% attempted' : s.explained + ' explained'}</span>
              </div>
            </button>`;
          }).join('')}
        </div>
      </section>`;

    app.querySelectorAll('[data-count]').forEach((el) =>
      countUp(el, +el.dataset.count));
    stagger('.tile', 60);
    stagger('.subject-card', 30);
  }

  /* ---------------------------------------------------------- practice */

  let session = null;
  const prefs = store.get('prefs', { size: 20, onlyKeyed: true, onlyExpl: false });

  function viewPractice(subjectId) {
    if (!subjectId) return viewPicker();
    const subject = BY_ID[subjectId];
    if (!subject) return viewPicker();

    app.innerHTML = `
      <section class="view practice">
        <div class="main">
          <div class="subject-head">
            <button class="btn ghost back" data-go="#/practice">${ICON.left} Subjects</button>
            <h2>${esc(subject.name)}</h2>
            <span class="chip">${num(subject.total)} total</span>
            <span class="chip">${num(subject.keyed)} keyed</span>
            <span class="chip">${num(subject.explained)} explained</span>
          </div>
          <div id="quiz"></div>
        </div>

        <aside class="side">
          <div class="side-card">
            <div class="side-title">This set</div>
            <div id="sideStats"></div>
          </div>
          <div class="side-card">
            <div class="side-title">Set up</div>
            <label class="side-row"><span>Questions</span>
              <select id="setSize">
                ${[10, 20, 50, 0].map((n) =>
                  `<option value="${n}" ${prefs.size === n ? 'selected' : ''}>${n || 'All'}</option>`
                ).join('')}
              </select>
            </label>
            <label class="side-check"><input type="checkbox" id="onlyKeyed"
              ${prefs.onlyKeyed ? 'checked' : ''}><span>Only with an answer key</span></label>
            <label class="side-check"><input type="checkbox" id="onlyExpl"
              ${prefs.onlyExpl ? 'checked' : ''}><span>Only with explanations</span></label>
            <button class="btn primary full" id="startBtn">${ICON.shuffle} New shuffled set</button>
          </div>
          <div class="side-card keys">
            <div class="side-title">Shortcuts</div>
            <div><kbd>1</kbd><kbd>2</kbd><kbd>3</kbd><kbd>4</kbd> answer</div>
            <div><kbd>&larr;</kbd><kbd>&rarr;</kbd> previous / next</div>
          </div>
        </aside>
      </section>`;

    const start = () => {
      prefs.size = +$('#setSize').value;
      prefs.onlyKeyed = $('#onlyKeyed').checked;
      prefs.onlyExpl = $('#onlyExpl').checked;
      store.set('prefs', prefs);

      let pool = subject.questions
        .map((q, i) => ({ q, i }))
        .filter(({ q }) => (!prefs.onlyKeyed || q.a >= 0) && (!prefs.onlyExpl || q.e));

      if (!pool.length) {
        session = null;
        $('#quiz').innerHTML = `<div class="empty card-empty">${ICON.empty}
          <p>Nothing in <b>${esc(subject.name)}</b> matches those filters.</p>
          <p style="font-size:14px">Try turning off &ldquo;only with explanations&rdquo;.</p></div>`;
        renderSide();
        return;
      }
      for (let i = pool.length - 1; i > 0; i--) {           // Fisher–Yates
        const j = Math.floor(Math.random() * (i + 1));
        [pool[i], pool[j]] = [pool[j], pool[i]];
      }
      if (prefs.size) pool = pool.slice(0, prefs.size);

      session = { subject, pool, pos: 0, picked: new Map(), correct: 0, wrong: 0 };
      renderQuestion();
    };

    $('#startBtn').addEventListener('click', () => { start(); toast('New set shuffled'); });
    ['setSize', 'onlyKeyed', 'onlyExpl'].forEach((id) =>
      $('#' + id).addEventListener('change', start));

    start();   // land straight on a question — no extra click needed
  }

  /** Side panel: progress ring + running score. */
  function renderSide() {
    const box = $('#sideStats');
    if (!box) return;
    const s = session;
    if (!s) { box.innerHTML = '<p class="side-muted">No active set.</p>'; return; }

    const done = s.correct + s.wrong;
    const acc = done ? pct(s.correct, done) : 0;
    box.innerHTML = `
      <div class="ring small" style="--p:${((s.pos + 1) / s.pool.length) * 100}">
        <b>${s.pos + 1}<em>/${s.pool.length}</em></b>
      </div>
      <div class="side-nums">
        <div><i class="dotc good"></i>${s.correct} correct</div>
        <div><i class="dotc bad"></i>${s.wrong} wrong</div>
        <div><i class="dotc neutral"></i>${acc}% accuracy</div>
      </div>`;
  }

  function viewPicker() {
    app.innerHTML = `
      <section class="view">
        <div class="hero"><h1>Pick a subject</h1>
          <p class="lede">Each set is shuffled, so you get a fresh order every time.</p></div>
        <div class="grid-subjects">
          ${SUBJECTS.map((s) => `
            <button class="subject-card" data-go="#/practice/${encodeURIComponent(s.id)}">
              <div class="row"><h3>${esc(s.name)}</h3><span class="chev">${ICON.chev}</span></div>
              <div class="meter-legend"><span>${num(s.total)} questions</span>
                <span>${num(s.explained)} explained</span></div>
            </button>`).join('')}
        </div>
      </section>`;
    stagger('.subject-card', 30);
  }

  function renderQuestion() {
    const s = session;
    const { q, i: qi } = s.pool[s.pos];
    const key = s.subject.id + ':' + qi;
    const picked = s.picked.get(s.pos);
    const answered = picked !== undefined;

    // short answers read better side by side than as full-width rows
    const compact = q.o.every((o) => o.length <= 26);

    $('#quiz').innerHTML = `
      <div class="progress" id="quizHead">
        <i style="width:${(s.pos / s.pool.length) * 100}%"></i></div>

      <article class="qcard" id="qcard">
        <div class="qtop">
          <div class="qmeta">
            <span class="qnum">Question ${s.pos + 1}<em> of ${s.pool.length}</em></span>
            ${q.c ? `<span>${esc(q.c)}</span>` : ''}
            ${q.g ? `<span>${esc(q.g)}</span>` : ''}
            ${q.a < 0 ? '<span class="warn">no answer key</span>' : ''}
          </div>
          <button class="star ${bookmarks.has(key) ? 'on' : ''}" id="starBtn"
                  aria-label="Bookmark question" aria-pressed="${bookmarks.has(key)}">
            ${bookmarks.has(key) ? ICON.starFill : ICON.star}</button>
        </div>

        <div class="qtext">${esc(q.q)}</div>
        <div class="options ${compact ? 'compact' : ''}" id="options">
          ${q.o.map((opt, k) => `
            <button class="opt" data-k="${k}" ${answered ? 'disabled' : ''}
                    style="animation-delay:${k * 45}ms">
              <span class="key">${esc(q.k[k] || String.fromCharCode(65 + k))}</span>
              <span class="txt">${esc(opt)}</span>
            </button>`).join('')}
        </div>
        <div id="feedback"></div>
      </article>

      <div class="quiz-foot">
        <button class="btn" id="prevBtn" ${s.pos === 0 ? 'disabled' : ''}>${ICON.left} Previous</button>
        <button class="btn" id="skipBtn">Skip</button>
        <span class="spacer"></span>
        <button class="btn primary" id="nextBtn">
          ${s.pos === s.pool.length - 1 ? 'Finish' : 'Next'} ${ICON.chev}</button>
      </div>`;

    renderSide();

    if (answered) paintAnswer(picked, true);

    $('#options').addEventListener('click', (e) => {
      const btn = e.target.closest('.opt');
      if (!btn || s.picked.has(s.pos)) return;
      choose(+btn.dataset.k);
    });
    $('#starBtn').addEventListener('click', () => {
      bookmarks.has(key) ? bookmarks.delete(key) : bookmarks.add(key);
      saveBookmarks();
      toast(bookmarks.has(key) ? 'Bookmarked' : 'Bookmark removed');
      renderQuestion();
    });
    $('#prevBtn').addEventListener('click', () => move(-1));
    $('#skipBtn').addEventListener('click', () => move(1));
    $('#nextBtn').addEventListener('click', () => move(1));
  }

  function choose(k) {
    const s = session;
    const { q, i: qi } = s.pool[s.pos];
    s.picked.set(s.pos, k);

    if (q.a >= 0) {
      if (k === q.a) s.correct++; else s.wrong++;
      const st = (stats[s.subject.id] ||= { seen: 0, correct: 0, wrong: 0 });
      st.seen++;
      k === q.a ? st.correct++ : st.wrong++;
      saveStats();
    }
    paintAnswer(k, false);
  }

  function paintAnswer(picked, silent) {
    const { q } = session.pool[session.pos];
    const opts = [...app.querySelectorAll('.opt')];
    opts.forEach((el, k) => {
      el.disabled = true;
      if (q.a >= 0 && k === q.a) el.classList.add('correct');
      else if (k === picked) el.classList.add(q.a >= 0 ? 'wrong' : 'muted');
      else el.classList.add('muted');
    });

    const right = q.a >= 0 && picked === q.a;
    const verdict = q.a < 0
      ? `<div class="verdict none">${ICON.info} This question has no answer key in the source book.</div>`
      : right
        ? `<div class="verdict good">${ICON.check} Correct</div>`
        : `<div class="verdict bad">${ICON.cross} Correct answer is ${esc(q.k[q.a] || '')}</div>`;

    $('#feedback').innerHTML = verdict + (q.e
      ? `<div class="explain"><h4>Explanation</h4><p>${esc(q.e)}</p></div>` : '');

    if (!silent) renderSide();   // running score lives in the side panel now
  }

  function move(delta) {
    const s = session;
    const next = s.pos + delta;
    if (next < 0) return;
    if (next >= s.pool.length) return renderResult();

    const card = $('#qcard');
    if (card) card.classList.add('leaving');
    setTimeout(() => { s.pos = next; renderQuestion(); }, 170);
  }

  function renderResult() {
    const s = session;
    const done = s.correct + s.wrong;
    const score = done ? pct(s.correct, done) : 0;

    $('#quiz').innerHTML = `
      <div class="result">
        <div class="ring" id="ring"><b>${score}%</b></div>
        <h2>${score >= 80 ? 'Excellent work' : score >= 50 ? 'Good going' : 'Keep practising'}</h2>
        <p style="color:var(--text-2);margin:8px 0 22px">
          You answered ${s.correct} of ${done} scored questions correctly
          ${s.pool.length - done ? `&middot; ${s.pool.length - done} skipped` : ''}.</p>
        <div class="quiz-foot" style="justify-content:center">
          <button class="btn primary" id="againBtn">${ICON.shuffle} Practise again</button>
          <button class="btn" data-go="#/home">All subjects</button>
        </div>
      </div>`;

    requestAnimationFrame(() => { $('#ring').style.setProperty('--p', score); });
    $('#againBtn').addEventListener('click', () => viewPractice(s.subject.id));
  }

  /* ---------------------------------------------------------- learn */

  let NOTES = null;          // { subjectId: [{title, blocks}] }, loaded on demand

  /** notes.js is ~2.4 MB, so it is only fetched the first time Learn is opened.
      A script tag (not fetch) keeps this working from file:// as well as http. */
  function loadNotes(then) {
    if (NOTES) return then();
    if (window.MCQ_NOTES) { NOTES = indexNotes(); return then(); }

    app.innerHTML = `<section class="view"><div class="empty">
      <div class="spinner"></div><p>Loading study material…</p></div></section>`;

    const tag = document.createElement('script');
    tag.src = 'notes.js';
    tag.onload = () => { NOTES = indexNotes(); then(); };
    tag.onerror = () => {
      app.innerHTML = `<section class="view"><div class="empty">${ICON.empty}
        <p>Could not load <code>notes.js</code>.</p>
        <p style="font-size:14px">Run <code>python build_site_data.py</code> to generate it.</p>
      </div></section>`;
    };
    document.head.appendChild(tag);
  }

  function indexNotes() {
    const out = {};
    for (const s of (window.MCQ_NOTES?.subjects || [])) out[s.file] = s.chapters;
    return out;
  }

  const noteName = (id) => PRETTY[id] || id.replace(/_/g, ' ');

  function viewLearn(subjectId, chapterIdx) {
    loadNotes(() => {
      const ids = Object.keys(NOTES);
      if (!subjectId || !NOTES[subjectId]) return learnIndex(ids);
      renderReader(subjectId, Math.max(0, Math.min(+chapterIdx || 0, NOTES[subjectId].length - 1)));
    });
  }

  function learnIndex(ids) {
    const card = (id) => {
      const chapters = NOTES[id];
      const words = chapters.reduce((a, c) =>
        a + c.blocks.reduce((n, b) => n + b.x.split(' ').length, 0), 0);
      return `
        <button class="subject-card" data-go="#/learn/${encodeURIComponent(id)}/0">
          <div class="row"><h3>${esc(noteName(id))}</h3><span class="chev">${ICON.chev}</span></div>
          <div class="meter-legend">
            <span>${chapters.length} chapters</span>
            <span>${num(Math.round(words / 1000))}k words</span>
          </div>
        </button>`;
    };
    const totalWords = ids.reduce((a, id) => a + NOTES[id].reduce((x, c) =>
      x + c.blocks.reduce((n, b) => n + b.x.split(' ').length, 0), 0), 0);

    app.innerHTML = `
      <section class="view">
        <div class="hero">
          <span class="eyebrow"><i class="dot"></i> Read before you drill</span>
          <h1>Study material</h1>
          <p class="lede">The chapter notes from the course books &mdash;
            ${num(Math.round(totalWords / 1000))}k words across ${ids.length} subjects,
            laid out to read rather than to page through.</p>
        </div>
        <div class="grid-subjects">${ids.map(card).join('')}</div>
      </section>`;
    stagger('.subject-card', 30);
  }

  function renderReader(id, idx) {
    const chapters = NOTES[id];
    const ch = chapters[idx];
    const readKey = `${id}:${idx}`;
    const read = new Set(store.get('read', []));

    // equations the PDF flattened beyond recovery are marked, not printed as rubble
    const eq = (s) => esc(s).replaceAll('⟨eq⟩', '<code class="eq">equation</code>');

    const body = ch.blocks.map((b) => {
      if (b.t === 'h2') return `<h3>${eq(b.x)}</h3>`;
      if (b.t === 'li') return `<li>${eq(b.x)}</li>`;
      return `<p>${eq(b.x)}</p>`;
    }).join('').replace(/(<li>.*?<\/li>)+/gs, (m) => `<ul>${m}</ul>`);

    app.innerHTML = `
      <section class="view learn">
        <aside class="toc">
          <button class="btn ghost back" data-go="#/learn">${ICON.left} All subjects</button>
          <div class="toc-title">${esc(noteName(id))}</div>
          <nav class="toc-list">
            ${chapters.map((c, i) => `
              <a href="#/learn/${encodeURIComponent(id)}/${i}"
                 class="${i === idx ? 'on' : ''} ${read.has(`${id}:${i}`) ? 'done' : ''}">
                <span class="n">${i + 1}</span>${esc(c.title)}</a>`).join('')}
          </nav>
        </aside>

        <article class="reader">
          <div class="reader-head">
            <span class="chip">Chapter ${idx + 1} of ${chapters.length}</span>
            <span class="chip">${num(ch.blocks.reduce((n, b) => n + b.x.split(' ').length, 0))} words</span>
            <span class="spacer"></span>
            <button class="btn ghost" id="markBtn">
              ${read.has(readKey) ? ICON.check + ' Read' : 'Mark as read'}</button>
          </div>
          <h1>${esc(ch.title)}</h1>
          <div class="prose">${body}</div>

          <div class="reader-foot">
            ${idx > 0 ? `<button class="btn" data-go="#/learn/${encodeURIComponent(id)}/${idx - 1}">
              ${ICON.left} Previous</button>` : '<span></span>'}
            <span class="spacer"></span>
            ${idx < chapters.length - 1
              ? `<button class="btn primary" data-go="#/learn/${encodeURIComponent(id)}/${idx + 1}">
                   Next chapter ${ICON.chev}</button>`
              : `<button class="btn primary" data-go="#/practice/${encodeURIComponent(id)}">
                   Practise this subject ${ICON.chev}</button>`}
          </div>
        </article>
      </section>`;

    $('#markBtn').addEventListener('click', () => {
      read.has(readKey) ? read.delete(readKey) : read.add(readKey);
      store.set('read', [...read]);
      toast(read.has(readKey) ? 'Marked as read' : 'Marked unread');
      renderReader(id, idx);
    });

    const active = app.querySelector('.toc-list a.on');
    if (active) active.scrollIntoView({ block: 'nearest' });
  }

  /* ---------------------------------------------------------- browse */

  const browseState = { term: '', subject: '', explained: false, saved: false, limit: 40 };

  function viewBrowse() {
    app.innerHTML = `
      <section class="view">
        <div class="hero"><h1>Browse the bank</h1>
          <p class="lede">Search every question, option and explanation.</p></div>
        <div class="toolbar">
          <label class="field">${ICON.search}
            <input id="q" type="search" placeholder="Search questions…" value="${esc(browseState.term)}">
          </label>
          <label class="field">
            <select id="subj">
              <option value="">All subjects</option>
              ${SUBJECTS.map((s) => `<option value="${esc(s.id)}"
                ${browseState.subject === s.id ? 'selected' : ''}>${esc(s.name)}</option>`).join('')}
            </select>
          </label>
          <label class="field"><input type="checkbox" id="fx" ${browseState.explained ? 'checked' : ''}>
            <span style="font-size:14.5px">With explanation</span></label>
          <label class="field"><input type="checkbox" id="fs" ${browseState.saved ? 'checked' : ''}>
            <span style="font-size:14.5px">Bookmarked only</span></label>
        </div>
        <div id="results"></div>
      </section>`;

    const rerun = () => { browseState.limit = 40; renderResults(); };
    let t;
    $('#q').addEventListener('input', (e) => {
      browseState.term = e.target.value;
      clearTimeout(t); t = setTimeout(rerun, 180);
    });
    $('#subj').addEventListener('change', (e) => { browseState.subject = e.target.value; rerun(); });
    $('#fx').addEventListener('change', (e) => { browseState.explained = e.target.checked; rerun(); });
    $('#fs').addEventListener('change', (e) => { browseState.saved = e.target.checked; rerun(); });
    renderResults();
  }

  function matches() {
    const term = browseState.term.trim().toLowerCase();
    const out = [];
    for (const s of SUBJECTS) {
      if (browseState.subject && s.id !== browseState.subject) continue;
      for (let i = 0; i < s.questions.length; i++) {
        const q = s.questions[i];
        if (browseState.explained && !q.e) continue;
        if (browseState.saved && !bookmarks.has(s.id + ':' + i)) continue;
        if (term) {
          const hay = (q.q + ' ' + q.o.join(' ') + ' ' + (q.e || '')).toLowerCase();
          if (!hay.includes(term)) continue;
        }
        out.push({ s, q, i });
        if (out.length > 4000) return out;   // hard cap keeps search snappy
      }
    }
    return out;
  }

  function renderResults() {
    const hits = matches();
    const shown = hits.slice(0, browseState.limit);
    const box = $('#results');

    if (!hits.length) {
      box.innerHTML = `<div class="empty">${ICON.empty}<p>Nothing matches those filters.</p></div>`;
      return;
    }

    box.innerHTML = `
      <div class="section-head"><h2>${num(hits.length)} question${hits.length === 1 ? '' : 's'}</h2>
        <p class="spacer">showing ${num(shown.length)}</p></div>
      <div class="qlist">
        ${shown.map(({ s, q, i }) => `
          <article class="qitem">
            <div class="qmeta"><span>${esc(s.name)}</span>${q.c ? `<span>${esc(q.c)}</span>` : ''}</div>
            <div class="q">${esc(q.q)}</div>
            <div class="opts">
              ${q.o.map((o, k) => `<div class="o ${q.a === k ? 'is-ans' : ''}">
                 <b>${esc(q.k[k] || String.fromCharCode(65 + k))}</b>${esc(o)}</div>`).join('')}
            </div>
            ${q.e ? `<details><summary>Show explanation</summary><p>${esc(q.e)}</p></details>` : ''}
          </article>`).join('')}
      </div>
      ${hits.length > shown.length
        ? `<div style="text-align:center;margin-top:20px">
             <button class="btn" id="moreBtn">Load more</button></div>` : ''}`;

    stagger('.qitem', 18);
    const more = $('#moreBtn');
    if (more) more.addEventListener('click', () => { browseState.limit += 40; renderResults(); });
  }

  /* ---------------------------------------------------------- routing */

  function moveInk() {
    const active = $('#tabs a.active');
    const ink = $('#tabInk');
    if (!active) { ink.style.opacity = 0; return; }
    ink.style.opacity = 1;
    ink.style.left = active.offsetLeft + 'px';
    ink.style.width = active.offsetWidth + 'px';
  }

  function route() {
    const hash = location.hash || '#/home';
    const [, name, arg] = hash.split('/');

    document.querySelectorAll('#tabs a').forEach((a) =>
      a.classList.toggle('active', a.dataset.tab === (name || 'home')));
    moveInk();

    if (name === 'practice') viewPractice(arg ? decodeURIComponent(arg) : '');
    else if (name === 'learn') viewLearn(arg ? decodeURIComponent(arg) : '', hash.split('/')[3]);
    else if (name === 'browse') viewBrowse();
    else viewHome();

    window.scrollTo({ top: 0, behavior: 'instant' });
  }

  document.addEventListener('click', (e) => {
    const go = e.target.closest('[data-go]');
    if (go) { e.preventDefault(); location.hash = go.dataset.go; }
  });

  document.addEventListener('keydown', (e) => {
    if (!session || !$('#qcard') || e.metaKey || e.ctrlKey || e.altKey) return;
    if (/^(INPUT|SELECT|TEXTAREA)$/.test(document.activeElement.tagName)) return;

    const k = e.key.toUpperCase();
    const idx = '1234'.indexOf(e.key) >= 0 ? '1234'.indexOf(e.key) : 'ABCD'.indexOf(k);
    if (idx >= 0 && !session.picked.has(session.pos)) {
      const btn = app.querySelector(`.opt[data-k="${idx}"]`);
      if (btn) { e.preventDefault(); choose(idx); }
    } else if (e.key === 'ArrowRight' || k === 'N') { e.preventDefault(); move(1); }
    else if (e.key === 'ArrowLeft' || k === 'P') { e.preventDefault(); move(-1); }
  });

  window.addEventListener('hashchange', route);
  window.addEventListener('resize', moveInk);

  if (!SUBJECTS.length) {
    app.innerHTML = `<div class="empty">${ICON.empty}
      <p>No data found. Run <code>build_site_data.py</code> to generate data.js.</p></div>`;
  } else {
    route();
  }
})();
