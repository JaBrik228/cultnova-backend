(function () {
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

    function ProjectsListingController() {
        if (document.body?.dataset.page !== "projects") {
            return;
        }

        this.endpoint = document.body.dataset.projectsEndpoint || "";
        this.pageSize = parseInteger(document.body.dataset.projectsPageSize, 3);
        this.feedElement = document.getElementById("projectsFeed");
        this.messageElement = document.getElementById("projectsMessage");
        this.statusElement = document.getElementById("projectsStatus");
        this.loadMoreButton = document.getElementById("projectsLoadMore");
        this.state = {
            page: parseInteger(document.body.dataset.projectsCurrentPage, 1),
            nextPage: parseInteger(document.body.dataset.projectsNextPage, null),
            hasNext: parseBoolean(document.body.dataset.projectsHasNext),
            isLoading: false,
            itemsCount: this.feedElement ? this.feedElement.children.length : 0,
        };
    }

    ProjectsListingController.prototype.init = function () {
        if (
            !this.endpoint ||
            !this.feedElement ||
            !this.messageElement ||
            !this.statusElement ||
            !this.loadMoreButton
        ) {
            return;
        }

        this.loadMoreButton.addEventListener("click", this.handleLoadMore.bind(this));
        this.updateLoadMoreButton();
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

            this.setStatus(result.items.length ? "Загружены дополнительные проекты." : "Дополнительных проектов не найдено.");
        } catch (error) {
            this.state.isLoading = false;
            this.showMessage({
                title: "Не удалось загрузить еще проекты.",
                copy: "Повторите попытку через несколько секунд.",
            });
            this.setStatus("Ошибка загрузки проектов.");
            console.error("[projects-listing] Failed to load more projects.", error);
        }

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
        var shouldShow = this.state.itemsCount > 0 && this.state.hasNext;

        this.loadMoreButton.hidden = !shouldShow;
        this.loadMoreButton.disabled = this.state.isLoading;
        this.loadMoreButton.textContent = this.state.isLoading
            ? "Загружаем..."
            : "Показать еще";
    };

    function bootstrap() {
        var controller = new ProjectsListingController();
        if (controller) {
            controller.init();
        }
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", bootstrap, { once: true });
    } else {
        bootstrap();
    }
})();
