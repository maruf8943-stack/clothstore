/* ============================================================
   ClothStore — Main JavaScript
   ============================================================ */

document.addEventListener('DOMContentLoaded', function () {

  // ---- Auto-dismiss flash messages ----
  const flashes = document.querySelectorAll('.flash');
  flashes.forEach(function (el) {
    setTimeout(function () {
      el.style.opacity = '0';
      el.style.transform = 'translateX(40px)';
      el.style.transition = 'all .4s ease';
      setTimeout(function () { el.remove(); }, 400);
    }, 3500);
  });

  // ---- Size button selector ----
  const sizeBtns = document.querySelectorAll('.size-btn');
  const sizeInput = document.getElementById('selected-size');
  sizeBtns.forEach(function (btn) {
    btn.addEventListener('click', function () {
      sizeBtns.forEach(function (b) { b.classList.remove('selected'); });
      btn.classList.add('selected');
      if (sizeInput) sizeInput.value = btn.dataset.size;
    });
  });
  // Select first size by default
  if (sizeBtns.length > 0) {
    sizeBtns[0].classList.add('selected');
    if (sizeInput) sizeInput.value = sizeBtns[0].dataset.size;
  }

  // ---- Quantity control ----
  const qtyInput = document.getElementById('qty-input');
  const qtyMinus = document.getElementById('qty-minus');
  const qtyPlus = document.getElementById('qty-plus');
  if (qtyMinus && qtyPlus && qtyInput) {
    qtyMinus.addEventListener('click', function () {
      var v = parseInt(qtyInput.value);
      if (v > 1) qtyInput.value = v - 1;
    });
    qtyPlus.addEventListener('click', function () {
      var v = parseInt(qtyInput.value);
      if (v < 99) qtyInput.value = v + 1;
    });
  }

  // ---- Filter chips (products page) ----
  const filterChips = document.querySelectorAll('.filter-chip[data-filter]');
  filterChips.forEach(function (chip) {
    chip.addEventListener('click', function () {
      var group = chip.dataset.group;
      var value = chip.dataset.filter;
      // Update URL with new filter
      var url = new URL(window.location.href);
      if (chip.classList.contains('active')) {
        url.searchParams.delete(group);
        chip.classList.remove('active');
      } else {
        document.querySelectorAll('.filter-chip[data-group="' + group + '"]').forEach(function (c) {
          c.classList.remove('active');
        });
        url.searchParams.set(group, value);
        chip.classList.add('active');
      }
      window.location.href = url.toString();
    });
  });

  // ---- Sort select ----
  var sortSelect = document.getElementById('sort-select');
  if (sortSelect) {
    sortSelect.addEventListener('change', function () {
      var url = new URL(window.location.href);
      url.searchParams.set('sort', sortSelect.value);
      window.location.href = url.toString();
    });
  }

  // ---- Cart qty update (inline) ----
  var cartQtyInputs = document.querySelectorAll('.cart-qty-input');
  cartQtyInputs.forEach(function (input) {
    input.addEventListener('change', function () {
      input.closest('form').submit();
    });
  });

  // ---- Mobile nav toggle ----
  var navToggle = document.getElementById('nav-toggle');
  var mobileNav = document.getElementById('mobile-nav');
  if (navToggle && mobileNav) {
    navToggle.addEventListener('click', function () {
      mobileNav.classList.toggle('open');
    });
  }

  // ---- Smooth scroll to section ----
  document.querySelectorAll('a[href^="#"]').forEach(function (anchor) {
    anchor.addEventListener('click', function (e) {
      var target = document.querySelector(this.getAttribute('href'));
      if (target) {
        e.preventDefault();
        target.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }
    });
  });

  // ---- Image gallery thumbnails (product detail) ----
  var thumbs = document.querySelectorAll('.gallery-thumb');
  var mainImg = document.getElementById('gallery-main-img');
  thumbs.forEach(function (thumb) {
    thumb.addEventListener('click', function () {
      if (mainImg) mainImg.src = thumb.dataset.src;
      thumbs.forEach(function (t) { t.classList.remove('active'); });
      thumb.classList.add('active');
    });
  });

});
