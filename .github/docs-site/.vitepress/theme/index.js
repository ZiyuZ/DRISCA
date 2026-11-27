import DefaultTheme from 'vitepress/theme';
import './style.css';

function setupImageLightbox() {
  if (typeof window === 'undefined' || window.__driscaLightboxReady) return;
  window.__driscaLightboxReady = true;

  let overlay = null;
  let zoomImg = null;
  let captionEl = null;
  let scale = 1;

  const close = () => {
    if (!overlay) return;
    overlay.classList.remove('is-open');
    document.body.style.overflow = '';
    scale = 1;
  };

  const applyScale = () => {
    if (zoomImg) {
      zoomImg.style.transform = `scale(${scale.toFixed(2)})`;
    }
  };

  const ensureOverlay = () => {
    if (overlay) return;
    overlay = document.createElement('div');
    overlay.className = 'drisca-lightbox';
    overlay.innerHTML =
      '<div class="drisca-lightbox-stage"><img class="drisca-lightbox-img" alt="" /></div>' +
      '<div class="drisca-lightbox-caption"></div>';
    zoomImg = overlay.querySelector('.drisca-lightbox-img');
    captionEl = overlay.querySelector('.drisca-lightbox-caption');

    overlay.addEventListener('click', (e) => {
      if (e.target === zoomImg) return;
      close();
    });

    zoomImg.addEventListener('click', () => {
      scale = scale > 1.05 ? 1 : 1.75;
      applyScale();
    });

    overlay.addEventListener(
      'wheel',
      (e) => {
        if (!overlay.classList.contains('is-open')) return;
        e.preventDefault();
        const delta = e.deltaY < 0 ? 0.2 : -0.2;
        scale = Math.min(4, Math.max(0.6, scale + delta));
        applyScale();
      },
      { passive: false },
    );

    window.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && overlay.classList.contains('is-open')) close();
    });

    document.body.appendChild(overlay);
  };

  document.addEventListener('click', (e) => {
    const target = e.target;
    if (!(target instanceof HTMLImageElement)) return;
    if (!target.closest('.drisca-figure') && !target.closest('.drisca-hero-showcase')) return;

    ensureOverlay();
    scale = 1;
    zoomImg.src = target.currentSrc || target.src;
    zoomImg.alt = target.alt || '';
    applyScale();
    captionEl.textContent = target.alt || '';
    captionEl.style.display = target.alt ? 'block' : 'none';
    overlay.classList.add('is-open');
    document.body.style.overflow = 'hidden';
  });
}

export default {
  extends: DefaultTheme,
  enhanceApp() {
    setupImageLightbox();
  },
};
