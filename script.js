// 모바일 메뉴 토글
const mobileMenuBtn = document.querySelector('.mobile-menu-btn');
const nav = document.querySelector('.nav');

mobileMenuBtn.addEventListener('click', () => {
    nav.classList.toggle('active');
});

// 네비게이션 링크 클릭 시 메뉴 닫기
const navLinks = document.querySelectorAll('.nav a');
navLinks.forEach(link => {
    link.addEventListener('click', () => {
        nav.classList.remove('active');
    });
});

// 부드러운 스크롤
document.querySelectorAll('a[href^="#"]').forEach(anchor => {
    anchor.addEventListener('click', function (e) {
        e.preventDefault();
        const target = document.querySelector(this.getAttribute('href'));
        if (target) {
            const headerHeight = document.querySelector('.header').offsetHeight;
            const targetPosition = target.offsetTop - headerHeight;
            window.scrollTo({
                top: targetPosition,
                behavior: 'smooth'
            });
        }
    });
});

// 스크롤 시 헤더 스타일 변경
const header = document.querySelector('.header');
window.addEventListener('scroll', () => {
    if (window.scrollY > 100) {
        header.style.boxShadow = '0 2px 20px rgba(0, 0, 0, 0.15)';
    } else {
        header.style.boxShadow = '0 2px 10px rgba(0, 0, 0, 0.1)';
    }
});

// 상담 폼 제출 - Google 스프레드시트 연동
const SCRIPT_URL = 'https://script.google.com/macros/s/AKfycbx5nP_Q7hM6oWC8KEw6NWQ4Yao4uTdFIDNMjcXRZPuV0dc_r7FRvKdlTSEE4CVdXXHl/exec';

const consultForm = document.getElementById('consultForm');
if (consultForm) {
    consultForm.addEventListener('submit', async function(e) {
        e.preventDefault();

        // 버튼 비활성화
        const submitBtn = this.querySelector('.btn-submit');
        const originalText = submitBtn.textContent;
        submitBtn.disabled = true;
        submitBtn.textContent = '전송 중...';

        // 체크박스 (복수 선택) 처리 - 학습 이유
        const reasonCheckboxes = this.querySelectorAll('input[name="reason"]:checked');
        const reasons = Array.from(reasonCheckboxes).map(cb => cb.parentElement.textContent.trim()).join(', ');

        // 폼 데이터 수집 (Apps Script 필드명과 일치)
        const data = {
            gender: this.gender.value,
            prevStudy: this.prevStudy.value,
            level: this.level.options[this.level.selectedIndex].text,
            reason: reasons,
            source: this.source.options[this.source.selectedIndex].text,
            contactMethod: this.contactMethod.options[this.contactMethod.selectedIndex].text,
            name: this.name.value,
            phone: this.phone.value,
            request: this.request.value
        };

        // 간단한 유효성 검사
        if (!data.name || !data.phone) {
            alert('이름과 연락처는 필수 입력 항목입니다.');
            submitBtn.disabled = false;
            submitBtn.textContent = originalText;
            return;
        }

        try {
            // Google Apps Script로 데이터 전송
            await fetch(SCRIPT_URL, {
                method: 'POST',
                mode: 'no-cors',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(data)
            });

            // 성공 메시지
            alert('상담 신청이 완료되었습니다!\n빠른 시일 내에 연락드리겠습니다.');

            // 폼 초기화
            this.reset();

        } catch (error) {
            console.error('Error:', error);
            alert('전송 중 오류가 발생했습니다. 다시 시도해주세요.');
        } finally {
            submitBtn.disabled = false;
            submitBtn.textContent = originalText;
        }
    });
}

// 스크롤 애니메이션 (Intersection Observer)
const observerOptions = {
    threshold: 0.1,
    rootMargin: '0px 0px -50px 0px'
};

const observer = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
        if (entry.isIntersecting) {
            entry.target.classList.add('visible');
        }
    });
}, observerOptions);

// 애니메이션 대상 요소들
document.querySelectorAll('.program-card, .teacher-card, .about-content, .contact-wrapper').forEach(el => {
    el.style.opacity = '0';
    el.style.transform = 'translateY(30px)';
    el.style.transition = 'opacity 0.6s ease, transform 0.6s ease';
    observer.observe(el);
});

// visible 클래스 스타일 추가
const style = document.createElement('style');
style.textContent = `
    .visible {
        opacity: 1 !important;
        transform: translateY(0) !important;
    }
`;
document.head.appendChild(style);

// 전화번호 자동 포맷팅
const phoneInput = document.getElementById('phone');
if (phoneInput) {
    phoneInput.addEventListener('input', function(e) {
        let value = e.target.value.replace(/[^0-9]/g, '');

        if (value.length > 3 && value.length <= 7) {
            value = value.slice(0, 3) + '-' + value.slice(3);
        } else if (value.length > 7) {
            value = value.slice(0, 3) + '-' + value.slice(3, 7) + '-' + value.slice(7, 11);
        }

        e.target.value = value;
    });
}

// About 섹션 이미지 슬라이더
const slides = document.querySelectorAll('.slider-container .slide');
const dots = document.querySelectorAll('.slider-dots .dot');
let currentSlide = 0;
let slideInterval;

function goToSlide(index) {
    slides.forEach(slide => slide.classList.remove('active'));
    dots.forEach(dot => dot.classList.remove('active'));

    slides[index].classList.add('active');
    dots[index].classList.add('active');
    currentSlide = index;
}

function nextSlide() {
    const next = (currentSlide + 1) % slides.length;
    goToSlide(next);
}

// 자동 슬라이드 시작
function startSlider() {
    slideInterval = setInterval(nextSlide, 4000);
}

// 자동 슬라이드 정지
function stopSlider() {
    clearInterval(slideInterval);
}

// 닷 클릭 이벤트
dots.forEach((dot, index) => {
    dot.addEventListener('click', () => {
        stopSlider();
        goToSlide(index);
        startSlider();
    });
});

// 슬라이더가 있을 때만 실행
if (slides.length > 0) {
    startSlider();
}

// 후기 슬라이더
const reviewsTrack = document.querySelector('.reviews-track');
const reviewSlides = document.querySelectorAll('.review-slide');
const prevBtn = document.querySelector('.slider-prev');
const nextBtn = document.querySelector('.slider-next');
const reviewsDotsContainer = document.querySelector('.reviews-dots');

let currentReviewIndex = 0;
let slidesPerView = 3;
let reviewAutoSlide;

// 화면 크기에 따른 슬라이드 수 계산
function updateSlidesPerView() {
    if (window.innerWidth <= 768) {
        slidesPerView = 1;
    } else if (window.innerWidth <= 1024) {
        slidesPerView = 2;
    } else {
        slidesPerView = 3;
    }
}

// 총 페이지 수 계산
function getTotalPages() {
    return Math.ceil(reviewSlides.length / slidesPerView);
}

// 인디케이터 생성
function createDots() {
    if (!reviewsDotsContainer) return;
    reviewsDotsContainer.innerHTML = '';
    const totalPages = getTotalPages();
    for (let i = 0; i < totalPages; i++) {
        const dot = document.createElement('span');
        dot.classList.add('dot');
        if (i === 0) dot.classList.add('active');
        dot.addEventListener('click', () => goToReview(i));
        reviewsDotsContainer.appendChild(dot);
    }
}

// 인디케이터 업데이트
function updateDots() {
    const dots = reviewsDotsContainer?.querySelectorAll('.dot');
    if (!dots) return;
    dots.forEach((dot, index) => {
        dot.classList.toggle('active', index === currentReviewIndex);
    });
}

// 슬라이드 이동
function goToReview(index) {
    const totalPages = getTotalPages();
    if (index < 0) index = totalPages - 1;
    if (index >= totalPages) index = 0;

    currentReviewIndex = index;

    const slideWidth = reviewSlides[0]?.offsetWidth + 25; // gap 포함
    const offset = currentReviewIndex * slidesPerView * slideWidth;

    if (reviewsTrack) {
        reviewsTrack.style.transform = `translateX(-${offset}px)`;
    }

    updateDots();
}

// 다음 슬라이드
function nextReview() {
    goToReview(currentReviewIndex + 1);
}

// 이전 슬라이드
function prevReview() {
    goToReview(currentReviewIndex - 1);
}

// 자동 슬라이드
function startReviewAutoSlide() {
    reviewAutoSlide = setInterval(nextReview, 5000);
}

function stopReviewAutoSlide() {
    clearInterval(reviewAutoSlide);
}

// 이벤트 리스너
if (prevBtn && nextBtn && reviewSlides.length > 0) {
    prevBtn.addEventListener('click', () => {
        stopReviewAutoSlide();
        prevReview();
        startReviewAutoSlide();
    });

    nextBtn.addEventListener('click', () => {
        stopReviewAutoSlide();
        nextReview();
        startReviewAutoSlide();
    });

    // 초기화
    updateSlidesPerView();
    createDots();
    startReviewAutoSlide();

    // 리사이즈 시 업데이트
    window.addEventListener('resize', () => {
        updateSlidesPerView();
        createDots();
        goToReview(0);
    });
}
