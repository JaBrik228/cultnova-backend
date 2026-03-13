(function () {
    function isActivationKey(event) {
        var key = event.key || event.code;
        return (
            key === "Enter" ||
            key === " " ||
            key === "Spacebar" ||
            key === "Space"
        );
    }

    function hydrateVideo(video) {
        if (!video) {
            return [];
        }

        var sources = video.querySelectorAll("source");
        var sourceObjects = [];
        for (var i = 0; i < sources.length; i++) {
            var source = sources[i];
            var src = source.getAttribute("src");
            var dataSrc = source.getAttribute("data-src");
            if (!src && dataSrc) {
                source.setAttribute("src", dataSrc);
                src = dataSrc;
            }
            if (src) {
                sourceObjects.push({
                    src: src,
                    type: source.getAttribute("type") || "video/mp4",
                });
            }
        }

        if (sourceObjects.length > 0 && video.dataset.videoLoaded !== "1") {
            video.dataset.videoLoaded = "1";
            video.load();
        }

        return sourceObjects;
    }

    function initPlayer(video, sourceObjects) {
        if (!window.videojs || typeof window.videojs !== "function") {
            return null;
        }

        try {
            var player = null;
            if (video.id && typeof window.videojs.getPlayer === "function") {
                player = window.videojs.getPlayer(video.id);
            }
            if (!player) {
                player = window.videojs(video, {
                    controls: true,
                    preload: "none",
                    autoplay: false,
                });
            }
            if (
                player &&
                typeof player.src === "function" &&
                sourceObjects &&
                sourceObjects.length > 0
            ) {
                player.src(sourceObjects);
            }
            return player;
        } catch (e) {
            return null;
        }
    }

    function tryPlay(video) {
        if (!video) {
            return null;
        }
        try {
            var promise = video.play();
            if (promise && typeof promise.catch === "function") {
                promise.catch(function () {});
            }
            return promise;
        } catch (e) {}
        return null;
    }

    function markStarted(wrapper) {
        wrapper.dataset.videoState = "started";
        wrapper.classList.remove("is-loading");
        wrapper.classList.add("is-started");
        wrapper.removeAttribute("tabindex");
        wrapper.removeAttribute("role");
        wrapper.removeAttribute("aria-label");

        var playerWrap = wrapper.querySelector("[data-video-player-wrap]");
        if (playerWrap) {
            playerWrap.setAttribute("aria-hidden", "false");
        }
    }

    function markError(wrapper) {
        wrapper.dataset.videoState = "error";
        wrapper.classList.remove("is-loading");
        wrapper.classList.remove("is-started");
        wrapper.classList.add("is-error");
    }

    function activateVideo(wrapper, event) {
        var state = wrapper.dataset.videoState || "idle";
        if (state === "loading" || state === "started") {
            return;
        }

        if (event) {
            if (event.type === "keydown" && !isActivationKey(event)) {
                return;
            }
            event.preventDefault();
            event.stopPropagation();
        }

        var video = wrapper.querySelector("video[data-lazy-video='1']");
        if (!video) {
            markError(wrapper);
            return;
        }

        wrapper.dataset.videoState = "loading";
        wrapper.classList.remove("is-error");
        wrapper.classList.add("is-loading");

        var playerWrap = wrapper.querySelector("[data-video-player-wrap]");
        if (playerWrap) {
            playerWrap.setAttribute("aria-hidden", "false");
        }

        var sources = hydrateVideo(video);
        if (!sources.length) {
            markError(wrapper);
            return;
        }

        video.classList.add("video-js");

        var started = false;
        var onStarted = function () {
            if (started) {
                return;
            }
            started = true;
            markStarted(wrapper);
        };
        video.addEventListener("loadeddata", onStarted, { once: true });
        video.addEventListener("playing", onStarted, { once: true });

        var player = initPlayer(video, sources);
        var playPromise = null;
        if (player && typeof player.play === "function") {
            try {
                playPromise = player.play();
            } catch (e) {
                playPromise = null;
            }
        }

        if (!playPromise) {
            playPromise = tryPlay(video);
        }

        if (playPromise && typeof playPromise.catch === "function") {
            playPromise.catch(function () {
                if (!started) {
                    wrapper.classList.remove("is-loading");
                }
            });
        }
    }

    function bindLazyVideo(wrapper) {
        if (!wrapper || wrapper.dataset.videoBound === "1") {
            return;
        }

        var activate = function (event) {
            activateVideo(wrapper, event);
        };

        var playButton = wrapper.querySelector("[data-video-play]");
        if (playButton) {
            playButton.addEventListener("click", activate);
            playButton.addEventListener("touchstart", activate, {
                passive: false,
            });
            playButton.addEventListener("keydown", activate);
            wrapper.dataset.videoBound = "1";
            return;
        }

        wrapper.setAttribute("tabindex", "0");
        wrapper.setAttribute("role", "button");
        wrapper.setAttribute("aria-label", "Запустить видео");
        wrapper.addEventListener("click", activate);
        wrapper.addEventListener("touchstart", activate, {
            passive: false,
        });
        wrapper.addEventListener("keydown", activate);
        wrapper.dataset.videoBound = "1";
    }

    function initLazyVideos() {
        var wrappers = document.querySelectorAll("[data-video-shell]");
        for (var i = 0; i < wrappers.length; i++) {
            bindLazyVideo(wrappers[i]);
        }
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", initLazyVideos, {
            once: true,
        });
    } else {
        initLazyVideos();
    }
})();
