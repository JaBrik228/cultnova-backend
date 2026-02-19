(function () {
  function getGap(track) {
    var style = window.getComputedStyle(track);
    var gap = parseFloat(style.columnGap || style.gap || "0");
    if (isNaN(gap)) {
      return 0;
    }
    return gap;
  }

  function initSlider(root) {
    var slider = root.querySelector(".articles-slider__slider");
    var track = root.querySelector(".articles-slider__track");
    var prevBtn = root.querySelector(".articles-slider__arrow--prev");
    var nextBtn = root.querySelector(".articles-slider__arrow--next");

    if (!slider || !track || !prevBtn || !nextBtn) {
      return;
    }

    var cards = track.querySelectorAll(".articles-slider__card");
    if (!cards.length) {
      prevBtn.disabled = true;
      nextBtn.disabled = true;
      return;
    }

    var currentIndex = 0;
    var maxIndex = 0;
    var cardStep = 0;

    var dragStartX = 0;
    var dragCurrentX = 0;
    var isDragging = false;
    var dragBaseOffset = 0;

    function recalc() {
      cards = track.querySelectorAll(".articles-slider__card");
      if (!cards.length) {
        currentIndex = 0;
        maxIndex = 0;
        cardStep = 0;
        update();
        return;
      }

      var cardWidth = cards[0].getBoundingClientRect().width;
      cardStep = cardWidth + getGap(track);

      var visibleCount = Math.max(1, Math.floor((slider.clientWidth + getGap(track)) / Math.max(cardStep, 1)));
      maxIndex = Math.max(0, cards.length - visibleCount);
      if (currentIndex > maxIndex) {
        currentIndex = maxIndex;
      }
      update();
    }

    function setOffset(offset, withTransition) {
      track.style.transition = withTransition ? "transform 0.35s ease" : "none";
      track.style.transform = "translateX(-" + offset + "px)";
    }

    function update() {
      setOffset(currentIndex * cardStep, true);
      prevBtn.disabled = currentIndex <= 0;
      nextBtn.disabled = currentIndex >= maxIndex;
    }

    function prev() {
      if (currentIndex <= 0) {
        return;
      }
      currentIndex -= 1;
      update();
    }

    function next() {
      if (currentIndex >= maxIndex) {
        return;
      }
      currentIndex += 1;
      update();
    }

    function startDrag(clientX) {
      isDragging = true;
      dragStartX = clientX;
      dragCurrentX = clientX;
      dragBaseOffset = currentIndex * cardStep;
      track.style.transition = "none";
    }

    function moveDrag(clientX) {
      if (!isDragging) {
        return;
      }
      dragCurrentX = clientX;
      var delta = dragStartX - dragCurrentX;
      var minOffset = 0;
      var maxOffset = maxIndex * cardStep;
      var nextOffset = dragBaseOffset + delta;
      if (nextOffset < minOffset) {
        nextOffset = minOffset;
      }
      if (nextOffset > maxOffset) {
        nextOffset = maxOffset;
      }
      setOffset(nextOffset, false);
    }

    function endDrag() {
      if (!isDragging) {
        return;
      }
      isDragging = false;

      var delta = dragStartX - dragCurrentX;
      var threshold = 50;

      if (delta > threshold && currentIndex < maxIndex) {
        currentIndex += 1;
      } else if (delta < -threshold && currentIndex > 0) {
        currentIndex -= 1;
      }
      update();
    }

    prevBtn.addEventListener("click", prev);
    nextBtn.addEventListener("click", next);

    slider.addEventListener("mousedown", function (event) {
      startDrag(event.clientX);
      event.preventDefault();
    });
    window.addEventListener("mousemove", function (event) {
      moveDrag(event.clientX);
    });
    window.addEventListener("mouseup", endDrag);

    slider.addEventListener(
      "touchstart",
      function (event) {
        if (!event.touches || !event.touches.length) {
          return;
        }
        startDrag(event.touches[0].clientX);
      },
      { passive: true }
    );
    slider.addEventListener(
      "touchmove",
      function (event) {
        if (!event.touches || !event.touches.length) {
          return;
        }
        moveDrag(event.touches[0].clientX);
      },
      { passive: true }
    );
    slider.addEventListener("touchend", endDrag);
    slider.addEventListener("touchcancel", endDrag);

    window.addEventListener("resize", function () {
      window.clearTimeout(initSlider._resizeTimer);
      initSlider._resizeTimer = window.setTimeout(recalc, 120);
    });

    recalc();
  }

  document.addEventListener("DOMContentLoaded", function () {
    var sliders = document.querySelectorAll(".articles-slider");
    for (var i = 0; i < sliders.length; i++) {
      initSlider(sliders[i]);
    }
  });
})();
