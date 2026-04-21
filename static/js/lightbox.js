(function () {
    var PAGE_CONFIG = {
        article: [
            ".article__text figure img",
            ".article__media-item img",
        ],
        project: [
            ".project__text figure img",
            ".project__feature-media img",
            ".project__gallery-item img",
        ],
    };

    var TRIGGER_CLASS = "lightbox-gallery__trigger";
    var dimensionPromises = new Map();

    function getPageType() {
        return document.body && document.body.dataset ? document.body.dataset.page : "";
    }

    function getSelectors(pageType) {
        return PAGE_CONFIG[pageType] || [];
    }

    function getPointer(event, image) {
        if (event && typeof event.clientX === "number" && typeof event.clientY === "number") {
            return {
                x: event.clientX,
                y: event.clientY,
            };
        }

        var rect = image.getBoundingClientRect();
        return {
            x: rect.left + rect.width / 2,
            y: rect.top + rect.height / 2,
        };
    }

    function isEligibleImage(image) {
        if (!(image instanceof HTMLImageElement)) {
            return false;
        }

        if (!image.currentSrc && !image.getAttribute("src")) {
            return false;
        }

        if (image.closest(".video-player")) {
            return false;
        }

        return true;
    }

    function getImageSrc(image) {
        return image.currentSrc || image.getAttribute("src") || image.src || "";
    }

    function getFallbackDimensions(image) {
        var rect = image.getBoundingClientRect();
        var pixelRatio = window.devicePixelRatio || 1;
        var width = Math.max(1, Math.round(rect.width * pixelRatio));
        var height = Math.max(1, Math.round(rect.height * pixelRatio));

        return {
            width: width,
            height: height,
        };
    }

    function getLoadedDimensions(image) {
        if (image.complete && image.naturalWidth > 0 && image.naturalHeight > 0) {
            return {
                width: image.naturalWidth,
                height: image.naturalHeight,
            };
        }

        return null;
    }

    function loadDimensions(image) {
        var src = getImageSrc(image);
        var loadedDimensions = getLoadedDimensions(image);

        if (loadedDimensions) {
            return Promise.resolve(loadedDimensions);
        }

        if (!src) {
            return Promise.resolve(getFallbackDimensions(image));
        }

        if (!dimensionPromises.has(src)) {
            dimensionPromises.set(
                src,
                new Promise(function (resolve) {
                    var probe = new Image();

                    probe.onload = function () {
                        resolve({
                            width: probe.naturalWidth || getFallbackDimensions(image).width,
                            height: probe.naturalHeight || getFallbackDimensions(image).height,
                        });
                    };

                    probe.onerror = function () {
                        resolve(getFallbackDimensions(image));
                    };

                    probe.src = src;
                })
            );
        }

        return dimensionPromises.get(src);
    }

    function setSlideDimensions(slide, dimensions) {
        slide.width = dimensions.width;
        slide.height = dimensions.height;
        slide.w = dimensions.width;
        slide.h = dimensions.height;
    }

    function warmSlide(slide) {
        return loadDimensions(slide.element).then(function (dimensions) {
            setSlideDimensions(slide, dimensions);
            return dimensions;
        });
    }

    function getCaptionFromFigure(image) {
        var figure = image.closest("figure");
        if (!figure) {
            return "";
        }

        var caption = figure.querySelector("figcaption");
        return caption ? caption.textContent.trim() : "";
    }

    function getCaptionFromSibling(image, selector) {
        var container = image.closest(selector);
        if (!container) {
            return "";
        }

        var sibling = container.nextElementSibling;
        if (sibling && sibling.classList.contains("article__media-caption")) {
            return sibling.textContent.trim();
        }
        if (sibling && sibling.classList.contains("project__media-caption")) {
            return sibling.textContent.trim();
        }

        return "";
    }

    function getCaption(image) {
        return (
            getCaptionFromFigure(image) ||
            getCaptionFromSibling(image, ".article__media-item") ||
            getCaptionFromSibling(image, ".project__feature-media") ||
            getCaptionFromSibling(image, ".project__gallery-item") ||
            ""
        );
    }

    function getPadding(slideData, viewportSize) {
        var hasCaption = Boolean(slideData && slideData.caption);
        var padding = {
            top: 36,
            right: 32,
            bottom: hasCaption ? 124 : 36,
            left: 32,
        };

        if (viewportSize.x <= 968) {
            padding.top = 56;
            padding.right = 20;
            padding.bottom = hasCaption ? 116 : 28;
            padding.left = 20;
        }

        if (viewportSize.x <= 768) {
            padding.top = 72;
            padding.right = 16;
            padding.bottom = hasCaption ? 108 : 24;
            padding.left = 16;
        }

        if (viewportSize.x <= 376) {
            padding.top = 64;
            padding.right = 12;
            padding.bottom = hasCaption ? 96 : 20;
            padding.left = 12;
        }

        return padding;
    }

    function createSlides(images) {
        return images.map(function (image) {
            var src = getImageSrc(image);

            return {
                src: src,
                msrc: src,
                alt: image.getAttribute("alt") || "",
                caption: getCaption(image),
                element: image,
                width: 0,
                height: 0,
                w: 0,
                h: 0,
            };
        });
    }

    function registerCaptionUI(lightbox) {
        lightbox.on("uiRegister", function () {
            var pswp = lightbox.pswp;

            pswp.ui.registerElement({
                name: "custom-caption",
                className: "pswp__custom-caption",
                appendTo: "root",
                order: 15,
                onInit: function (element, instance) {
                    function updateCaption() {
                        var currentSlide = instance.currSlide;
                        var caption = currentSlide && currentSlide.data ? currentSlide.data.caption : "";
                        element.textContent = caption || "";
                        element.hidden = !caption;
                    }

                    instance.on("change", updateCaption);
                    instance.on("afterInit", updateCaption);
                    updateCaption();
                },
            });
        });
    }

    function createLightbox(slides) {
        var lightbox = new PhotoSwipeLightbox({
            dataSource: slides,
            pswpModule: PhotoSwipe,
            loop: true,
            wheelToZoom: true,
            bgOpacity: 0.92,
            closeTitle: "Закрыть галерею",
            zoomTitle: "Увеличить или уменьшить изображение",
            arrowPrevTitle: "Предыдущее изображение",
            arrowNextTitle: "Следующее изображение",
            errorMsg: "Не удалось загрузить изображение",
            indexIndicatorSep: " из ",
            paddingFn: getPadding,
        });

        registerCaptionUI(lightbox);
        lightbox.init();

        return lightbox;
    }

    function bindImage(image, index, total, lightbox, slides) {
        if (image.dataset.lightboxBound === "1") {
            return;
        }

        image.dataset.lightboxBound = "1";
        image.classList.add(TRIGGER_CLASS);
        image.tabIndex = 0;
        image.setAttribute("role", "button");
        image.setAttribute("aria-haspopup", "dialog");
        image.setAttribute("aria-label", "Открыть изображение " + (index + 1) + " из " + total);

        function open(event) {
            event.preventDefault();
            warmSlide(slides[index]).finally(function () {
                lightbox.loadAndOpen(index, undefined, getPointer(event, image));
            });
        }

        image.addEventListener("click", open);
        image.addEventListener("keydown", function (event) {
            if (event.key === "Enter" || event.key === " ") {
                open(event);
            }
        });
    }

    function collectImages(pageType) {
        var selectors = getSelectors(pageType);
        var images = [];
        var seen = new Set();

        selectors.forEach(function (selector) {
            document.querySelectorAll(selector).forEach(function (image) {
                if (!isEligibleImage(image) || seen.has(image)) {
                    return;
                }

                seen.add(image);
                images.push(image);
            });
        });

        return images;
    }

    function initLightboxGallery() {
        var pageType = getPageType();

        if (!PAGE_CONFIG[pageType]) {
            return;
        }

        if (typeof PhotoSwipeLightbox !== "function" || typeof PhotoSwipe !== "function") {
            return;
        }

        var images = collectImages(pageType);

        if (!images.length) {
            return;
        }

        var slides = createSlides(images);
        var lightbox = createLightbox(slides);

        slides.forEach(function (slide) {
            warmSlide(slide);
        });

        images.forEach(function (image, index) {
            bindImage(image, index, images.length, lightbox, slides);
        });
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", initLightboxGallery, { once: true });
    } else {
        initLightboxGallery();
    }
})();
