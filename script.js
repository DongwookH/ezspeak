/* ============================================================================
   EZSPEAK — interactions (vanilla JS, no dependencies)
   - mobile nav toggle
   - sticky header state
   - smooth in-page scroll (with fixed-header offset)
   - scroll reveal (IntersectionObserver)
   - phone auto-format
   - consult form submit -> Google Apps Script
   - Reviews carousel (responsive, dots, arrows, autoplay)
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
    if (from && /^[a-z0-9-]{1,80}$/.test(from)) return from === 'region' ? 'region' : 'region/' + from;
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
})();
