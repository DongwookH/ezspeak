/* ============================================================================
   EZSPEAK — interactions (vanilla JS, no dependencies)
   - mobile nav toggle
   - sticky header state
   - smooth in-page scroll (with fixed-header offset)
   - scroll reveal (IntersectionObserver)
   - phone auto-format
   - consult form submit -> Google Apps Script
   - Reviews carousel (responsive, dots, arrows, autoplay)
   - Textbook sliders (교재 1종 = 1장, 자동 넘김·점·스와이프·키보드)
   - Textbook image stage (표지·속지를 한 장씩 크게, 교재 슬라이더 안)
   ========================================================================== */
(function () {
  'use strict';

  /* ---- Mobile menu -------------------------------------------------------- */
  const mobileMenuBtn = document.querySelector('.mobile-menu-btn');
  const nav = document.querySelector('.nav');

  if (mobileMenuBtn && nav) {
    const closeMenu = () => {
      nav.classList.remove('active');
      mobileMenuBtn.classList.remove('open');
      mobileMenuBtn.setAttribute('aria-expanded', 'false');
    };
    mobileMenuBtn.addEventListener('click', () => {
      const open = nav.classList.toggle('active');
      mobileMenuBtn.classList.toggle('open', open);
      mobileMenuBtn.setAttribute('aria-expanded', String(open));
    });
    nav.querySelectorAll('a').forEach((link) => link.addEventListener('click', closeMenu));
  }

  /* ---- Sticky header state ------------------------------------------------ */
  const header = document.querySelector('.header');
  if (header) {
    const onScroll = () => header.classList.toggle('scrolled', window.scrollY > 20);
    window.addEventListener('scroll', onScroll, { passive: true });
    onScroll();
  }

  /* ---- In-page anchor scrolling -------------------------------------------
     네이티브 앵커 동작 사용(즉시 점프). 고정 헤더 오프셋은 CSS의
     scroll-padding-top 이 처리한다. JS preventDefault + smooth scrollTo 방식은
     일부 렌더러에서 클릭이 무반응이 되는 문제가 있어 제거 */

  /* ---- Scroll reveal ------------------------------------------------------ */
  const revealEls = document.querySelectorAll('.reveal');
  if ('IntersectionObserver' in window && revealEls.length) {
    const io = new IntersectionObserver((entries, obs) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          entry.target.classList.add('is-in');
          obs.unobserve(entry.target);
        }
      });
    }, { threshold: 0.12, rootMargin: '0px 0px -40px 0px' });
    revealEls.forEach((el) => io.observe(el));
    /* observer가 발화하지 않는 환경(일부 임베디드 브라우저)에서도
       콘텐츠가 숨겨진 채 남지 않도록 하는 안전 폴백 */
    setTimeout(() => {
      if (!document.querySelector('.reveal.is-in')) {
        revealEls.forEach((el) => el.classList.add('is-in'));
      }
    }, 1500);
  } else {
    revealEls.forEach((el) => el.classList.add('is-in'));
  }

  /* ---- Phone auto-format -------------------------------------------------- */
  const phoneInput = document.getElementById('phone');
  if (phoneInput) {
    phoneInput.addEventListener('input', (e) => {
      let v = e.target.value.replace(/[^0-9]/g, '');
      if (v.length > 3 && v.length <= 7) {
        v = v.slice(0, 3) + '-' + v.slice(3);
      } else if (v.length > 7) {
        v = v.slice(0, 3) + '-' + v.slice(3, 7) + '-' + v.slice(7, 11);
      }
      e.target.value = v;
    });
  }

  /* ---- Consult form -> /api/lead (시트 저장 + 텔레그램 알림) ---------------- */
  const consultForm = document.getElementById('consultForm');

  /* 유입 페이지: ?from={slug} → region/{slug}, 없으면 referrer, 없으면 direct */
  function resolveSourcePage(search, referrer, origin) {
    const from = new URLSearchParams(search).get('from');
    if (from && /^[a-z0-9-]{1,80}$/.test(from)) {
      /* 지역 허브·칼럼·교재 페이지는 그대로, 나머지는 지역 슬러그 */
      return ['region', 'guide', 'textbooks'].includes(from) ? from : 'region/' + from;
    }
    if (referrer) {
      try {
        const u = new URL(referrer);
        return u.origin === origin ? u.pathname : u.hostname;
      } catch (_) { /* 잘못된 referrer는 direct로 */ }
    }
    return 'direct';
  }

  if (consultForm) {
    /* 사이트 안에서 이동해도 첫 유입을 유지 (저장소 차단 환경이면 매번 계산) */
    let sourcePage;
    try { sourcePage = sessionStorage.getItem('ezs_source_page'); } catch (_) {}
    if (!sourcePage) {
      sourcePage = resolveSourcePage(location.search, document.referrer, location.origin);
      try { sessionStorage.setItem('ezs_source_page', sourcePage); } catch (_) {}
    }
    if (consultForm.sourcePage) consultForm.sourcePage.value = sourcePage;

    /* 희망 테스트 날짜: 오늘(로컬 기준) 이후만 */
    if (consultForm.testDate) {
      const d = new Date();
      d.setMinutes(d.getMinutes() - d.getTimezoneOffset());
      consultForm.testDate.min = d.toISOString().slice(0, 10);
    }

    consultForm.addEventListener('submit', async function (e) {
      e.preventDefault();

      const submitBtn = this.querySelector('.btn-submit');
      const originalText = submitBtn.textContent;
      submitBtn.disabled = true;
      submitBtn.textContent = '전송 중...';

      const reasons = Array.from(this.querySelectorAll('input[name="reason"]:checked'))
        .map((cb) => cb.parentElement.textContent.trim())
        .join(', ');

      const data = {
        gender: this.gender.value,
        prevStudy: this.prevStudy.value,
        level: this.level.options[this.level.selectedIndex].text,
        reason: reasons,
        source: this.source.options[this.source.selectedIndex].text,
        contactMethod: this.contactMethod.options[this.contactMethod.selectedIndex].text,
        name: this.name.value,
        phone: this.phone.value,
        request: this.request.value,
        testDate: this.testDate.value,
        testTime: this.testTime.value,
        sourcePage: this.sourcePage.value,
      };

      if (!data.name || !data.phone || !data.testDate || !data.testTime) {
        alert('이름, 연락처, 희망 레벨테스트 일시는 필수 입력 항목입니다.');
        submitBtn.disabled = false;
        submitBtn.textContent = originalText;
        return;
      }

      try {
        const res = await fetch('/api/lead', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(data),
        });
        const result = await res.json().catch(() => ({}));
        if (!res.ok || !result.ok) throw new Error(result.error || res.status);
        alert('상담 신청이 완료되었습니다!\n빠른 시일 내에 연락드리겠습니다.');
        this.reset();
      } catch (err) {
        console.error('Error:', err);
        alert('전송 중 오류가 발생했습니다. 다시 시도해주세요.');
      } finally {
        submitBtn.disabled = false;
        submitBtn.textContent = originalText;
      }
    });
  }


  /* 틀이 가로로 밀리면 즉시 되돌린다 (overflow: clip 미지원 브라우저 대비) */
  document.querySelectorAll('.bs-viewport, .stage-view').forEach((v) => {
    v.addEventListener('scroll', () => { if (v.scrollLeft) v.scrollLeft = 0; }, { passive: true });
  });

  /* ---- Reviews carousel --------------------------------------------------- */
  const reviewsTrack = document.querySelector('.reviews-track');
  const reviewSlides = document.querySelectorAll('.review-slide');
  const prevBtn = document.querySelector('.slider-prev');
  const nextBtn = document.querySelector('.slider-next');
  const reviewsDotsContainer = document.querySelector('.reviews-dots');
  const REVIEW_GAP = 24;

  let currentReviewIndex = 0;
  let slidesPerView = 3;
  let reviewAutoSlide;

  function updateSlidesPerView() {
    if (window.innerWidth <= 720) slidesPerView = 1;
    else if (window.innerWidth <= 940) slidesPerView = 2;
    else slidesPerView = 3;
  }
  function getTotalPages() { return Math.ceil(reviewSlides.length / slidesPerView); }

  function createDots() {
    if (!reviewsDotsContainer) return;
    reviewsDotsContainer.innerHTML = '';
    const total = getTotalPages();
    for (let i = 0; i < total; i++) {
      const dot = document.createElement('span');
      dot.className = 'dot' + (i === 0 ? ' active' : '');
      dot.addEventListener('click', () => { stopReviewAutoSlide(); goToReview(i); startReviewAutoSlide(); });
      reviewsDotsContainer.appendChild(dot);
    }
  }
  function updateDots() {
    if (!reviewsDotsContainer) return;
    reviewsDotsContainer.querySelectorAll('.dot').forEach((d, i) => {
      d.classList.toggle('active', i === currentReviewIndex);
    });
  }
  function goToReview(index) {
    const total = getTotalPages();
    if (index < 0) index = total - 1;
    if (index >= total) index = 0;
    currentReviewIndex = index;

    const slideW = (reviewSlides[0] ? reviewSlides[0].offsetWidth : 0) + REVIEW_GAP;
    const offset = currentReviewIndex * slidesPerView * slideW;
    if (reviewsTrack) reviewsTrack.style.transform = `translateX(-${offset}px)`;
    updateDots();
  }
  function nextReview() { goToReview(currentReviewIndex + 1); }
  function prevReview() { goToReview(currentReviewIndex - 1); }
  function startReviewAutoSlide() { reviewAutoSlide = setInterval(nextReview, 5000); }
  function stopReviewAutoSlide() { clearInterval(reviewAutoSlide); }

  if (prevBtn && nextBtn && reviewSlides.length > 0) {
    prevBtn.addEventListener('click', () => { stopReviewAutoSlide(); prevReview(); startReviewAutoSlide(); });
    nextBtn.addEventListener('click', () => { stopReviewAutoSlide(); nextReview(); startReviewAutoSlide(); });

    updateSlidesPerView();
    createDots();
    startReviewAutoSlide();

    let resizeTimer;
    window.addEventListener('resize', () => {
      clearTimeout(resizeTimer);
      resizeTimer = setTimeout(() => {
        updateSlidesPerView();
        createDots();
        goToReview(0);
      }, 150);
    });
  }

  /* ---- Textbook sliders (교재 슬라이더 A/B) --------------------------------
     후기 캐러셀과 같은 transform 방식. 슬라이드가 100% 폭이라 translateX(-n*100%)
     만으로 위치가 정해져 resize 처리 불필요. hover/focus/정지 버튼 시 멈춤,
     reduced-motion 이면 자동 넘김 없음 */
  const reduceMotion = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  /* 교재 이미지 스테이지: 표지 → 속지 1 → 속지 2 를 한 장씩 크게.
     교재 페이지(api/textbooks.py 인라인 JS)와 같은 클래스·동작. 스테이지 안의 키·스와이프는
     여기서 멈춰(stopPropagation) 바깥 교재 슬라이더로 가지 않는다. onUser: 사용자가 넘겼을 때 */
  function initStage(root, onUser) {
    const track = root.querySelector('.stage-track');
    const items = Array.from(root.querySelectorAll('.stage-item'));
    const tabs = Array.from(root.querySelectorAll('.stage-tabs button'));
    const count = root.querySelector('.stage-count');
    const n = items.length;
    let i = 0;
    const eager = (k) => { const img = items[k] && items[k].querySelector('img'); if (img) img.loading = 'eager'; };

    function go(k, user) {
      i = (k + n) % n;
      track.style.transform = `translateX(-${i * 100}%)`;
      items.forEach((it, j) => { it.inert = j !== i; });
      tabs.forEach((t, j) => t.setAttribute('aria-current', String(j === i)));
      if (count) count.textContent = `${i + 1} / ${n}`;
      if (user) { eager(i); eager((i + 1) % n); if (onUser) onUser(); }
    }

    root.querySelector('.stage-prev').addEventListener('click', () => go(i - 1, true));
    root.querySelector('.stage-next').addEventListener('click', () => go(i + 1, true));
    tabs.forEach((t, j) => t.addEventListener('click', () => go(j, true)));
    root.addEventListener('keydown', (e) => {
      if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
      e.preventDefault();
      e.stopPropagation();
      go(i + (e.key === 'ArrowRight' ? 1 : -1), true);
    });
    const view = root.querySelector('.stage-view');
    let x0 = null, y0 = 0;
    view.addEventListener('touchstart', (e) => { e.stopPropagation(); x0 = e.touches[0].clientX; y0 = e.touches[0].clientY; }, { passive: true });
    view.addEventListener('touchend', (e) => {
      e.stopPropagation();
      if (x0 === null) return;
      const dx = e.changedTouches[0].clientX - x0;
      const dy = e.changedTouches[0].clientY - y0;
      x0 = null;
      if (Math.abs(dx) > 40 && Math.abs(dx) > Math.abs(dy)) go(i + (dx < 0 ? 1 : -1), true);
    }, { passive: true });

    go(0, false);
    /* 전환 애니메이션 없이 즉시 표지로 (들어오는 교재가 화면 밖에 있을 때 호출) */
    function reset() {
      if (i === 0) return;
      track.style.transition = 'none';
      go(0, false);
      void track.offsetWidth;
      track.style.transition = '';
    }
    return { reset, eager };
  }

  /* 필터 값 표시 순서(데이터: api/_data/textbooks.json 의 levels / purposes) */
  const BOOK_FILTERS = [
    ['levels', '레벨', ['입문', '초급', '중급', '고급']],
    ['purposes', '목적', ['일상회화', '비즈니스', '여행', '유학·어학연수', '시사·토론', '문법·어휘', '쓰기', '말하기 시험', '키즈·주니어', '중등 내신']],
  ];

  function initBookSlider(root) {
    const viewport = root.querySelector('.bs-viewport');
    const track = root.querySelector('.bs-track');
    const slides = Array.from(root.querySelectorAll('.bs-slide'));
    const dotsBox = root.querySelector('.bs-dots');
    const controls = root.querySelector('.bs-controls');
    const pauseBtn = root.querySelector('.bs-pause');
    if (!track || !slides.length) return;

    /* 슬라이드마다 레벨·목적(시리즈 전 권 합집합)과 이름 */
    const meta = slides.map((s) => ({
      levels: (s.dataset.levels || '').split(',').filter(Boolean),
      purposes: (s.dataset.purposes || '').split(',').filter(Boolean),
      name: (s.getAttribute('aria-label') || '').replace(/^[^:]*:\s*/, ''),
    }));
    const picked = { levels: '', purposes: '' };
    let active = slides.map((_, i) => i);  // 필터에 맞는 슬라이드 번호
    let index = 0;                          // active 안에서의 위치
    let dots = [];
    let timer = null;
    let hovering = false;
    let focused = false;
    let userPaused = reduceMotion;
    /* 이미지를 넘기면 보고 있는 중이므로 교재 자동 넘김은 정지 상태로 */
    const stages = slides.map((s) => {
      const st = s.querySelector('.stage');
      return st ? initStage(st, () => { if (!userPaused) { userPaused = true; sync(); } }) : null;
    });

    /* ---- 필터 바(JS 가 있을 때만 생김 — 없으면 전체 슬라이드 그대로) ---- */
    const bar = document.createElement('div');
    bar.className = 'bs-filter';
    bar.setAttribute('role', 'group');
    bar.setAttribute('aria-label', (root.getAttribute('aria-label') || '교재') + ' 골라 보기');
    const groups = BOOK_FILTERS.map(([key, label, order]) => {
      const values = order.filter((v) => meta.some((m) => m[key].includes(v)));
      const row = document.createElement('div');
      row.className = 'bs-frow';
      const cap = document.createElement('span');
      cap.className = 'bs-flabel';
      cap.textContent = label;
      const opts = document.createElement('div');
      opts.className = 'bs-fopts';
      const btns = [''].concat(values).map((v) => {
        const b = document.createElement('button');
        b.type = 'button';
        b.textContent = v || '전체';
        b.setAttribute('aria-pressed', String(v === ''));
        b.addEventListener('click', () => { picked[key] = v; applyFilter(); });
        opts.appendChild(b);
        return [v, b];
      });
      row.append(cap, opts);
      bar.appendChild(row);
      return [key, btns];
    });
    root.before(bar);

    const empty = document.createElement('div');
    empty.className = 'bs-empty';
    empty.hidden = true;
    empty.innerHTML = '<p>조건에 맞는 교재가 없습니다.</p><button type="button">필터 초기화</button>';
    empty.querySelector('button').addEventListener('click', () => {
      picked.levels = picked.purposes = '';
      applyFilter();
    });
    viewport.after(empty);

    function applyFilter() {
      groups.forEach(([key, btns]) => btns.forEach(([v, b]) => b.setAttribute('aria-pressed', String(picked[key] === v))));
      active = slides.map((_, i) => i).filter((i) =>
        (!picked.levels || meta[i].levels.includes(picked.levels)) &&
        (!picked.purposes || meta[i].purposes.includes(picked.purposes)));
      slides.forEach((s, i) => { s.hidden = !active.includes(i); });
      const none = !active.length;
      empty.hidden = !none;
      viewport.hidden = none;
      if (controls) controls.hidden = none;
      dotsBox.textContent = '';
      dots = active.map((_, p) => {
        const b = document.createElement('button');
        b.type = 'button';
        b.setAttribute('aria-label', `${p + 1}번째 교재 보기`);
        b.addEventListener('click', () => goTo(p));
        dotsBox.appendChild(b);
        return b;
      });
      track.style.transition = 'none';  // 필터 전환은 애니메이션 없이 첫 교재로
      goTo(0);
      void track.offsetWidth;
      track.style.transition = '';
      sync();
    }

    function goTo(p) {
      const n = active.length;
      if (!n) return;
      index = (p + n) % n;
      const cur = active[index];
      const next = active[(index + 1) % n];
      track.style.transform = `translateX(-${index * 100}%)`;  // 숨긴 슬라이드는 자리를 차지하지 않는다
      slides.forEach((s, k) => {
        const on = k === cur;
        s.inert = !on;
        s.setAttribute('aria-hidden', String(!on));
        const pos = active.indexOf(k);
        if (pos >= 0) s.setAttribute('aria-label', `${pos + 1} / ${n}: ${meta[k].name}`);
        const st = stages[k];
        if (!st) return;
        /* 들어오는 교재는 표지(1/3)부터. 현재 교재는 표지·속지 1, 다음 교재는 표지만 미리 받기 */
        if (on) { st.reset(); st.eager(0); st.eager(1); } else if (k === next) st.eager(0);
      });
      dots.forEach((d, k) => d.setAttribute('aria-current', String(k === index)));
    }

    function sync() {
      clearInterval(timer);
      const running = !userPaused && !hovering && !focused && active.length > 1;
      if (running) timer = setInterval(() => goTo(index + 1), 5000);
      viewport.setAttribute('aria-live', running ? 'off' : 'polite');
      if (pauseBtn) {
        pauseBtn.textContent = userPaused ? '재생' : '정지';
        pauseBtn.setAttribute('aria-label', userPaused ? '자동 넘김 재생' : '자동 넘김 정지');
      }
    }

    root.querySelector('.bs-prev').addEventListener('click', () => { goTo(index - 1); sync(); });
    root.querySelector('.bs-next').addEventListener('click', () => { goTo(index + 1); sync(); });
    if (pauseBtn) pauseBtn.addEventListener('click', () => { userPaused = !userPaused; sync(); });

    root.addEventListener('mouseenter', () => { hovering = true; sync(); });
    root.addEventListener('mouseleave', () => { hovering = false; sync(); });
    root.addEventListener('focusin', () => { focused = true; sync(); });
    root.addEventListener('focusout', (e) => { if (!root.contains(e.relatedTarget)) { focused = false; sync(); } });
    root.addEventListener('keydown', (e) => {
      if (e.key === 'ArrowLeft') { e.preventDefault(); goTo(index - 1); }
      else if (e.key === 'ArrowRight') { e.preventDefault(); goTo(index + 1); }
    });

    let x0 = null, y0 = 0;
    viewport.addEventListener('touchstart', (e) => { x0 = e.touches[0].clientX; y0 = e.touches[0].clientY; }, { passive: true });
    viewport.addEventListener('touchend', (e) => {
      if (x0 === null) return;
      const dx = e.changedTouches[0].clientX - x0;
      const dy = e.changedTouches[0].clientY - y0;
      x0 = null;
      if (Math.abs(dx) > 40 && Math.abs(dx) > Math.abs(dy)) { goTo(index + (dx < 0 ? 1 : -1)); sync(); }
    }, { passive: true });

    applyFilter();
  }

  document.querySelectorAll('.book-slider').forEach(initBookSlider);
})();
