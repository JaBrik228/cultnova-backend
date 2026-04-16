(function () {
    var PROJECTS_PAGE = "projects";
    var SHELL_SELECTOR = "#projectsListingShell";
    var CATEGORY_TAGS_SELECTOR = ".projects__tags";
    var pendingCategoryNavigationUrl = "";

    function parseInteger(value, fallback) {
        var parsed = Number.parseInt(value, 10);
        return Number.isFinite(parsed) ? parsed : fallback;
    }

    function parseBoolean(value) {
        return value === true || value === "true" || value === "1" || value === 1;
    }

    function createRequestError(response) {
        var error = new Error("Не удалось загрузить проекты.");
        error.status = response.status;
        return error;
    }

    function isProjectsPage() {
        return document.body?.dataset.page === PROJECTS_PAGE;
    }

    function isElement(value) {
        return typeof Element !== "undefined" && value instanceof Element;
    }

    function getProjectsShell() {
        if (!isProjectsPage()) {
            return null;
        }

        return document.querySelector(SHELL_SELECTOR);
    }

    function syncDocumentTitle(shellElement) {
        var nextTitle = shellElement?.dataset.pageTitle;
        if (typeof nextTitle === "string" && nextTitle.trim()) {
            document.title = nextTitle.trim();
        }
    }

    function getRequestElement(detail) {
        if (isElement(detail?.requestConfig?.elt)) {
            return detail.requestConfig.elt;
        }

        if (isElement(detail?.elt)) {
            return detail.elt;
        }

        if (isElement(detail?.target)) {
            return detail.target;
        }

        return null;
    }

    function isProjectsCategoryRequest(detail) {
        var element = getRequestElement(detail);

        if (isElement(element) && element.closest(CATEGORY_TAGS_SELECTOR)) {
            return true;
        }

        var triggeringTarget = detail?.triggeringEvent?.target;
        return isElement(triggeringTarget) && Boolean(triggeringTarget.closest(CATEGORY_TAGS_SELECTOR));
    }

    function getRequestPath(detail) {
        var requestPath = detail?.pathInfo?.requestPath || detail?.requestConfig?.path || "";
        if (typeof requestPath === "string" && requestPath.trim()) {
            return requestPath;
        }

        var element = getRequestElement(detail);
        if (isElement(element)) {
            var link = element.closest("a[href]");
            if (link?.href) {
                return link.href;
            }
        }

        return "";
    }

    function setShellBusyState(isBusy) {
        var shellElement = getProjectsShell();
        if (shellElement) {
            shellElement.setAttribute("aria-busy", isBusy ? "true" : "false");
        }
    }

    function ProjectsListingController(shellElement) {
        this.shellElement = shellElement;
        this.endpoint = shellElement?.dataset.projectsEndpoint || "";
        this.pageSize = parseInteger(shellElement?.dataset.projectsPageSize, 3);
        this.feedElement = shellElement?.querySelector("#projectsFeed") || null;
        this.messageElement = shellElement?.querySelector("#projectsMessage") || null;
        this.statusElement = shellElement?.querySelector("#projectsStatus") || null;
        this.loadMoreButton = shellElement?.querySelector("#projectsLoadMore") || null;
        this.state = {
            page: parseInteger(shellElement?.dataset.projectsCurrentPage, 1),
            nextPage: parseInteger(shellElement?.dataset.projectsNextPage, null),
            hasNext: parseBoolean(shellElement?.dataset.projectsHasNext),
            isLoading: false,
            itemsCount: this.feedElement ? this.feedElement.children.length : 0,
        };
    }

    ProjectsListingController.prototype.init = function () {
        if (
            !this.shellElement ||
            this.shellElement.dataset.projectsListingBound === "1" ||
            !this.endpoint ||
            !this.messageElement ||
            !this.statusElement ||
            !this.loadMoreButton
        ) {
            return;
        }

        this.shellElement.dataset.projectsListingBound = "1";
        this.loadMoreButton.addEventListener("click", this.handleLoadMore.bind(this));
        this.updateLoadMoreButton();
    };

    ProjectsListingController.prototype.setBusyState = function (isBusy) {
        this.shellElement?.setAttribute("aria-busy", isBusy ? "true" : "false");

        if (this.feedElement) {
            this.feedElement.setAttribute("aria-busy", isBusy ? "true" : "false");
        }
    };

    ProjectsListingController.prototype.handleLoadMore = async function () {
        if (
            this.state.isLoading ||
            !this.state.hasNext ||
            !Number.isFinite(this.state.nextPage)
        ) {
            return;
        }

        this.setStatus("Загружаем еще проекты.");
        this.state.isLoading = true;
        this.setBusyState(true);
        this.updateLoadMoreButton();
        this.clearMessage();

        try {
            var payload = await this.fetchPayload(this.state.nextPage);
            var result = this.normalizePayload(payload, this.state.nextPage);

            this.state.page = result.page;
            this.state.nextPage = result.nextPage;
            this.state.hasNext = result.hasNext;
            this.state.isLoading = false;

            this.renderItems(result.items);
            this.state.itemsCount += result.items.length;

            this.setStatus(
                result.items.length
                    ? "Загружены дополнительные проекты."
                    : "Дополнительных проектов не найдено.",
            );
        } catch (error) {
            this.state.isLoading = false;
            this.showMessage({
                title: "Не удалось загрузить еще проекты.",
                copy: "Повторите попытку через несколько секунд.",
            });
            this.setStatus("Ошибка загрузки проектов.");
            console.error("[projects-listing] Failed to load more projects.", error);
        }

        this.setBusyState(false);
        this.updateLoadMoreButton();
    };

    ProjectsListingController.prototype.fetchPayload = async function (page) {
        var requestUrl = new URL(this.endpoint, window.location.origin);
        requestUrl.searchParams.set("limit", String(this.pageSize));
        requestUrl.searchParams.set("page", String(page));

        var response = await fetch(requestUrl.toString(), {
            headers: {
                Accept: "application/json",
            },
        });

        if (!response.ok) {
            throw createRequestError(response);
        }

        return response.json();
    };

    ProjectsListingController.prototype.normalizePayload = function (payload, requestedPage) {
        var items = Array.isArray(payload?.data) ? payload.data : [];
        var currentPage = parseInteger(payload?.current_page ?? payload?.page, requestedPage);
        var hasNext = parseBoolean(payload?.has_next ?? payload?.hasNext);
        var nextPage = hasNext
            ? parseInteger(payload?.next_page ?? payload?.nextPage, currentPage + 1)
            : null;

        return {
            items: items,
            page: currentPage,
            hasNext: hasNext,
            nextPage: nextPage,
        };
    };

    ProjectsListingController.prototype.renderItems = function (items) {
        if (!this.feedElement || !items.length) {
            return;
        }

        var fragment = document.createDocumentFragment();
        var self = this;

        items.forEach(function (project) {
            fragment.append(self.createProjectCard(project));
        });

        this.feedElement.append(fragment);
    };

    ProjectsListingController.prototype.createProjectCard = function (project) {
        var article = document.createElement("article");
        article.className = "projects__card projects__card--enter";

        var link = document.createElement("a");
        link.className = "projects__card-link";
        link.href = typeof project?.url === "string" && project.url.trim() ? project.url : "#";

        var imageWrap = document.createElement("div");
        imageWrap.className = "projects__card-image";

        if (typeof project?.preview === "string" && project.preview.trim()) {
            var image = document.createElement("img");
            image.className = "projects__card-img";
            image.src = project.preview;
            image.alt =
                (typeof project?.preview_image_alt === "string" && project.preview_image_alt.trim()) ||
                (typeof project?.title === "string" && project.title.trim()) ||
                "Изображение проекта";
            image.width = 600;
            image.height = 440;
            image.loading = "lazy";
            image.decoding = "async";
            image.setAttribute("fetchpriority", "low");
            imageWrap.append(image);
        } else {
            var fallback = document.createElement("div");
            fallback.className = "projects__card-image-fallback";
            fallback.textContent = "Изображение проекта временно недоступно";
            imageWrap.append(fallback);
        }

        var content = document.createElement("div");
        content.className = "projects__card-content";

        if (typeof project?.category_title === "string" && project.category_title.trim()) {
            var category = document.createElement("span");
            category.className = "projects__card-category";
            category.textContent = project.category_title.trim();
            content.append(category);
        }

        var title = document.createElement("h2");
        title.className = "projects__card-title";
        title.textContent =
            (typeof project?.title === "string" && project.title.trim()) ||
            "Проект без названия";
        content.append(title);

        if (typeof project?.excerpt === "string" && project.excerpt.trim()) {
            var excerpt = document.createElement("p");
            excerpt.className = "projects__card-excerpt";
            excerpt.textContent = project.excerpt.trim();
            content.append(excerpt);
        }

        link.append(imageWrap, content);
        article.append(link);

        return article;
    };

    ProjectsListingController.prototype.showMessage = function (options) {
        this.messageElement.hidden = false;
        this.messageElement.replaceChildren();

        var title = document.createElement("p");
        title.className = "projects__message-title";
        title.textContent = options.title;

        var copy = document.createElement("p");
        copy.className = "projects__message-copy";
        copy.textContent = options.copy;

        this.messageElement.append(title, copy);
    };

    ProjectsListingController.prototype.clearMessage = function () {
        this.messageElement.hidden = true;
        this.messageElement.replaceChildren();
    };

    ProjectsListingController.prototype.setStatus = function (text) {
        this.statusElement.textContent = text || "";
    };

    ProjectsListingController.prototype.updateLoadMoreButton = function () {
        if (!this.loadMoreButton) {
            return;
        }

        var shouldShow = this.state.itemsCount > 0 && this.state.hasNext;

        this.loadMoreButton.hidden = !shouldShow;
        this.loadMoreButton.disabled = this.state.isLoading;
        this.loadMoreButton.textContent = this.state.isLoading
            ? "Загружаем..."
            : "Показать еще";
    };

    function bootstrap() {
        var shellElement = getProjectsShell();
        if (!shellElement) {
            return;
        }

        syncDocumentTitle(shellElement);

        var controller = new ProjectsListingController(shellElement);
        controller.init();
    }

    function handleCategoryNavigationStart(event) {
        if (!isProjectsCategoryRequest(event.detail)) {
            return;
        }

        pendingCategoryNavigationUrl = getRequestPath(event.detail);
        setShellBusyState(true);
    }

    function handleCategoryNavigationSettle() {
        setShellBusyState(false);
        pendingCategoryNavigationUrl = "";
        bootstrap();
    }

    function handleCategoryNavigationFailure(event) {
        if (!isProjectsCategoryRequest(event.detail)) {
            return;
        }

        setShellBusyState(false);

        var navigationUrl = getRequestPath(event.detail) || pendingCategoryNavigationUrl;
        pendingCategoryNavigationUrl = "";

        if (navigationUrl) {
            window.location.assign(navigationUrl);
        }
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", bootstrap, { once: true });
    } else {
        bootstrap();
    }

    document.body?.addEventListener("htmx:beforeRequest", handleCategoryNavigationStart);
    document.body?.addEventListener("htmx:afterSwap", handleCategoryNavigationSettle);
    document.body?.addEventListener("htmx:historyRestore", handleCategoryNavigationSettle);
    document.body?.addEventListener("htmx:responseError", handleCategoryNavigationFailure);
    document.body?.addEventListener("htmx:sendError", handleCategoryNavigationFailure);
    document.body?.addEventListener("htmx:swapError", handleCategoryNavigationFailure);
})();
