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

  /* ---- Consult form -> Google Apps Script --------------------------------- */
  const SCRIPT_URL = 'https://script.google.com/macros/s/AKfycbx5nP_Q7hM6oWC8KEw6NWQ4Yao4uTdFIDNMjcXRZPuV0dc_r7FRvKdlTSEE4CVdXXHl/exec';
  const consultForm = document.getElementById('consultForm');

  if (consultForm) {
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
      };

      if (!data.name || !data.phone) {
        alert('이름과 연락처는 필수 입력 항목입니다.');
        submitBtn.disabled = false;
        submitBtn.textContent = originalText;
        return;
      }

      try {
        await fetch(SCRIPT_URL, {
          method: 'POST',
          mode: 'no-cors',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(data),
        });
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
