/* ECHOES companion — shared by the voice assistant (/) and the camera (/camera).
 *
 * 1. speak(text, priority)  — Arabic text-to-speech with a small queue; safety
 *    warnings jump the queue.
 * 2. Ears — continuous speech recognition. Every final sentence goes to
 *    /api/companion/hear:
 *      - wake phrase (or the patient's button)  -> answer now
 *      - a question from someone else           -> wait N seconds (13 by
 *        default); if the patient starts talking, cancel; otherwise answer
 *        for him. Very personal questions are never answered.
 *      - a sentence that mentions a memory      -> gentle reminder
 */
(function () {
  const Companion = {
    rate: 0.9, volume: 1, muted: false,
    onLog: null,            // (text, cls) => void
    onState: null,          // (kind, text) => void
    onPending: null,        // (secondsLeft|null, question) => void
    replyDelay: 13,
  };

  // ---------------------------------------------------------- speech out --
  const queue = [];
  let speaking = false;
  let arVoice = null;
  function pickVoice() {
    const vs = (window.speechSynthesis && speechSynthesis.getVoices()) || [];
    arVoice = vs.find(v => v.lang && v.lang.toLowerCase().startsWith('ar')) || null;
  }
  if ('speechSynthesis' in window) {
    pickVoice();
    speechSynthesis.onvoiceschanged = pickVoice;
  }

  function next() {
    if (speaking || !queue.length) return;
    const text = queue.shift();
    if (Companion.muted || !('speechSynthesis' in window)) { next(); return; }
    const u = new SpeechSynthesisUtterance(text);
    u.lang = 'ar-SA'; u.rate = Companion.rate; u.volume = Companion.volume;
    if (arVoice) u.voice = arVoice;
    speaking = true;
    Ears.pause();                         // never hear ourselves
    state('speaking', 'أتحدث…');
    u.onend = u.onerror = () => {
      speaking = false;
      setTimeout(() => { Ears.resume(); if (!queue.length) state(Ears.on ? 'listening' : '', Ears.on ? 'أسمع…' : 'جاهز'); next(); }, 250);
    };
    speechSynthesis.speak(u);
  }

  Companion.speak = function (text, priority) {
    if (!text) return;
    if (priority) {
      queue.unshift(text);
      if (speaking) { try { speechSynthesis.cancel(); } catch (e) {} }
    } else {
      if (queue.includes(text)) return;
      queue.push(text);
    }
    next();
  };
  Companion.isSpeaking = () => speaking;

  function log(text, cls) { if (Companion.onLog) Companion.onLog(text, cls); }
  function state(kind, text) { if (Companion.onState) Companion.onState(kind, text); }

  // ------------------------------------------------- pending reply (13 s) --
  let pending = null;   // {timer, ticker, answer, question}
  function cancelPending(reason) {
    if (!pending) return;
    clearTimeout(pending.timer); clearInterval(pending.ticker);
    if (reason) log('المريض ردّ بنفسه — لن أجيب عنه.', 'note');
    pending = null;
    if (Companion.onPending) Companion.onPending(null, '');
  }
  function schedule(answer, question, seconds) {
    cancelPending();
    let left = seconds;
    pending = { answer, question };
    if (Companion.onPending) Companion.onPending(left, question);
    pending.ticker = setInterval(() => {
      left -= 1;
      if (Companion.onPending && pending) Companion.onPending(left, question);
    }, 1000);
    pending.timer = setTimeout(() => {
      const p = pending; cancelPending();
      if (!p) return;
      log(p.answer, 'bot');
      Companion.speak(p.answer);
    }, seconds * 1000);
  }
  Companion.cancelPending = cancelPending;

  // ------------------------------------------------------------ hearing ---
  let directNext = false;
  Companion.askNext = () => { directNext = true; state('listening', 'تفضّل، اسأل…'); };

  Companion.hear = async function (text) {
    text = (text || '').trim();
    if (!text) return;
    // Any speech while a reply is pending means the patient answered.
    if (pending) {
      // Someone re-asking / asking again is not the patient answering.
      const looksLikeQuestion = /[؟?]$/.test(text) ||
        /^(كم|وش|ايش|إيش|شو|شنو|ما|ماذا|هل|متى|وين|أين|كيف|ليش|لماذا|مين|من|تعرف|تذكر|عد)(\s|$)/.test(text);
      if (looksLikeQuestion) { cancelPending(false); }
      else { cancelPending(true); log(text, 'me'); return; }
    }
    const direct = directNext; directNext = false;
    log(text, 'me');
    try {
      const r = await fetch('/api/companion/hear', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text, direct, image: Companion.getFrame ? Companion.getFrame() : null }),
      });
      const d = await r.json();
      if (d.addressed) {
        if (d.answer) { log(d.answer, d.kind === 'answered' ? 'bot' : 'unsure'); Companion.speak(d.answer); }
      } else if (d.is_question) {
        if (d.kind === 'private') {
          log('سؤال عن معلومة خاصة جدًا — لن أجيب عنه.', 'note');
        } else if (d.kind === 'answered' && d.answer) {
          schedule(d.answer, text, d.wait_seconds || Companion.replyDelay);
        }
      } else if (d.reminder && d.reminder.text) {
        log(d.reminder.text, 'memory');
        Companion.speak(d.reminder.text);
      }
    } catch (e) {
      log('تعذّر الاتصال بالمساعد.', 'unsure');
    }
  };

  // --------------------------------------------------------------- ears ---
  const Ears = {
    on: false, rec: null, paused: false, restart: null,
    supported: !!(window.SpeechRecognition || window.webkitSpeechRecognition),
    init() {
      const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
      if (!SR) return null;
      const r = new SR();
      r.lang = 'ar-SA'; r.continuous = true; r.interimResults = true;
      r.onresult = (ev) => {
        for (let i = ev.resultIndex; i < ev.results.length; i++) {
          const t = ev.results[i][0].transcript;
          if (ev.results[i].isFinal) Companion.hear(t);
          else if (pending && t.trim().length > 6 && !/^(كم|وش|ايش|شو|ما|هل|متى|وين|كيف|مين|تعرف|عد)/.test(t.trim())) cancelPending(true);   // patient started replying
          else state('listening', t.trim() || 'أسمع…');
        }
      };
      r.onerror = (e) => {
        if (e.error === 'not-allowed' || e.error === 'service-not-allowed') {
          Ears.on = false; state('', 'الميكروفون ممنوع — اسمح للمتصفح');
        } else if (e.error === 'audio-capture') {
          Ears.on = false; state('', 'لا يوجد ميكروفون');
        }
      };
      r.onend = () => { if (Ears.on && !Ears.paused) Ears.kick(); };
      return r;
    },
    kick() {
      clearTimeout(this.restart);
      this.restart = setTimeout(() => {
        if (!this.on || this.paused) return;
        try { this.rec.start(); } catch (e) {}
      }, 300);
    },
    start() {
      if (!this.supported) { log('المتصفح لا يدعم التعرف على الكلام. استخدم Chrome.', 'unsure'); return false; }
      if (!this.rec) this.rec = this.init();
      this.on = true; this.paused = false;
      try { this.rec.start(); } catch (e) {}
      state('listening', 'أسمع…');
      return true;
    },
    stop() {
      this.on = false; clearTimeout(this.restart);
      if (this.rec) { try { this.rec.stop(); } catch (e) {} }
      cancelPending();
      state('', 'متوقف');
    },
    pause() { this.paused = true; if (this.rec && this.on) { try { this.rec.stop(); } catch (e) {} } },
    resume() { if (!this.paused) return; this.paused = false; if (this.on) this.kick(); },
  };
  Companion.ears = Ears;

  fetch('/api/companion/config').then(r => r.json()).then(c => {
    Companion.replyDelay = c.reply_delay || 13;
    Companion.config = c;
  }).catch(() => {});

  window.Companion = Companion;
})();
