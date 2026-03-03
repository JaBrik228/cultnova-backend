(function () {
  if (!window.Jodit) {
    return;
  }

  const editors = new Map();
  const previewClassNames = ["article-editor-preview", "article__text"];
  const colorSchemeQuery = window.matchMedia
    ? window.matchMedia("(prefers-color-scheme: dark)")
    : null;
  let modalElements = null;
  let activeEditor = null;
  let themeSyncRegistered = false;

  function getStoredThemeMode() {
    const currentTheme = document.documentElement.dataset.theme;
    if (currentTheme === "light" || currentTheme === "dark" || currentTheme === "auto") {
      return currentTheme;
    }

    try {
      const storedTheme = window.localStorage ? window.localStorage.getItem("theme") : null;
      if (storedTheme === "light" || storedTheme === "dark" || storedTheme === "auto") {
        return storedTheme;
      }
    } catch (error) {
      return "auto";
    }

    return "auto";
  }

  function isDarkThemeActive() {
    const themeMode = getStoredThemeMode();
    if (themeMode === "dark") {
      return true;
    }

    if (themeMode === "light") {
      return false;
    }

    return Boolean(colorSchemeQuery && colorSchemeQuery.matches);
  }

  function getJoditTheme() {
    return isDarkThemeActive() ? "dark" : "default";
  }

  function applyEditorTheme(editor) {
    if (!editor || !editor.container) {
      return;
    }

    const theme = getJoditTheme();
    const isDark = theme === "dark";

    editor.o.theme = theme;
    editor.container.dataset.theme = theme;
    editor.container.classList.toggle("jodit_theme_dark", isDark);
    editor.container.classList.toggle("jodit_theme_default", !isDark);
  }

  function applyEditorPreviewClasses(editor) {
    if (!editor) {
      return;
    }

    const editableArea = editor.editor || editor.container.querySelector(".jodit-wysiwyg");
    if (!editableArea) {
      return;
    }

    previewClassNames.forEach(function (className) {
      editableArea.classList.add(className);
    });
  }

  function syncAllEditorsTheme() {
    editors.forEach(function (editor) {
      applyEditorTheme(editor);
    });
  }

  function registerThemeSync() {
    if (themeSyncRegistered) {
      return;
    }

    themeSyncRegistered = true;

    const observer = new MutationObserver(function (mutations) {
      const themeChanged = mutations.some(function (mutation) {
        return mutation.type === "attributes" && mutation.attributeName === "data-theme";
      });

      if (themeChanged) {
        syncAllEditorsTheme();
      }
    });

    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["data-theme"],
    });

    if (colorSchemeQuery) {
      if (typeof colorSchemeQuery.addEventListener === "function") {
        colorSchemeQuery.addEventListener("change", syncAllEditorsTheme);
      } else if (typeof colorSchemeQuery.addListener === "function") {
        colorSchemeQuery.addListener(syncAllEditorsTheme);
      }
    }

    window.addEventListener("load", syncAllEditorsTheme);
  }

  function getCsrfToken() {
    const formToken = document.querySelector("input[name=csrfmiddlewaretoken]");
    if (formToken && formToken.value) {
      return formToken.value;
    }

    const cookie = document.cookie
      .split(";")
      .map((item) => item.trim())
      .find((item) => item.startsWith("csrftoken="));

    return cookie ? decodeURIComponent(cookie.split("=")[1]) : "";
  }

  function buildControl(name, tagName, label) {
    return {
      name: name,
      tooltip: label,
      text: label,
      exec: function (editor) {
        editor.execCommand("formatBlock", false, tagName);
        editor.synchronizeValues();
      },
    };
  }

  function createModal() {
    if (modalElements) {
      return modalElements;
    }

    const overlay = document.createElement("div");
    overlay.className = "article-richtext-modal";
    overlay.hidden = true;
    overlay.innerHTML = [
      '<div class="article-richtext-modal__dialog" role="dialog" aria-modal="true" aria-labelledby="article-richtext-modal-title">',
      '<div class="article-richtext-modal__header">',
      '<h2 id="article-richtext-modal-title">Inline image</h2>',
      '<button type="button" class="article-richtext-modal__close" aria-label="Close">x</button>',
      "</div>",
      '<form class="article-richtext-modal__form">',
      '<label class="article-richtext-modal__field">',
      "<span>Image</span>",
      '<input type="file" name="file" accept=".jpg,.jpeg,.png,.webp,image/jpeg,image/png,image/webp" required />',
      "</label>",
      '<label class="article-richtext-modal__field">',
      "<span>Alt text</span>",
      '<input type="text" name="alt" maxlength="255" required />',
      "</label>",
      '<label class="article-richtext-modal__field">',
      "<span>Caption</span>",
      '<input type="text" name="caption" maxlength="255" />',
      "</label>",
      '<div class="article-richtext-modal__actions">',
      '<button type="button" class="article-richtext-modal__button article-richtext-modal__button--ghost" data-action="cancel">Cancel</button>',
      '<button type="submit" class="article-richtext-modal__button">Insert image</button>',
      "</div>",
      '<p class="article-richtext-modal__error" hidden></p>',
      "</form>",
      "</div>",
    ].join("");

    document.body.appendChild(overlay);

    const form = overlay.querySelector("form");
    const error = overlay.querySelector(".article-richtext-modal__error");

    function closeModal() {
      activeEditor = null;
      error.hidden = true;
      error.textContent = "";
      form.reset();
      overlay.hidden = true;
    }

    overlay.addEventListener("click", function (event) {
      if (
        event.target === overlay ||
        event.target.closest("[data-action='cancel']") ||
        event.target.closest(".article-richtext-modal__close")
      ) {
        closeModal();
      }
    });

    form.addEventListener("submit", function (event) {
      event.preventDefault();

      if (!activeEditor) {
        closeModal();
        return;
      }

      const textarea = activeEditor.element;
      const uploadUrl = textarea.dataset.inlineImageUploadUrl;
      if (!uploadUrl) {
        activeEditor.message.error("Inline image upload URL is not configured.");
        return;
      }

      const formData = new FormData(form);
      const submitButton = form.querySelector("button[type='submit']");
      submitButton.disabled = true;
      error.hidden = true;
      error.textContent = "";

      fetch(uploadUrl, {
        method: "POST",
        headers: {
          "X-CSRFToken": getCsrfToken(),
        },
        body: formData,
        credentials: "same-origin",
      })
        .then(function (response) {
          return response.json().then(function (payload) {
            return { ok: response.ok, payload: payload };
          });
        })
        .then(function (result) {
          if (!result.ok || !result.payload.success) {
            throw new Error(result.payload.error || "Image upload failed.");
          }

          activeEditor.s.insertHTML(result.payload.html);
          activeEditor.synchronizeValues();
          closeModal();
        })
        .catch(function (uploadError) {
          error.hidden = false;
          error.textContent = uploadError.message;
        })
        .finally(function () {
          submitButton.disabled = false;
        });
    });

    modalElements = { overlay: overlay, form: form, error: error, close: closeModal };
    return modalElements;
  }

  function openInlineImageModal(editor) {
    const modal = createModal();
    activeEditor = editor;
    modal.overlay.hidden = false;
    const altInput = modal.form.querySelector("input[name='alt']");
    altInput.focus();
  }

  function createEditor(textarea) {
    if (!textarea || editors.has(textarea)) {
      return;
    }

    const editor = window.Jodit.make(textarea, {
      height: 420,
      theme: getJoditTheme(),
      editorClassName: previewClassNames.join(" "),
      toolbarSticky: false,
      toolbarAdaptive: false,
      textIcons: false,
      sourceEditor: "area",
      askBeforePasteHTML: false,
      askBeforePasteFromWord: false,
      removeButtons: ["image", "video", "file", "font", "fontsize", "brush", "about", "print"],
      buttons: [
        "paragraph",
        "h2",
        "h3",
        "h4",
        "|",
        "lead",
        "|",
        "bold",
        "italic",
        "underline",
        "strikethrough",
        "|",
        "ul",
        "ol",
        "|",
        "link",
        "table",
        "inlineImage",
        "|",
        "source",
        "undo",
        "redo",
        "fullsize",
      ],
      buttonsMD: [
        "paragraph",
        "h2",
        "h3",
        "h4",
        "lead",
        "bold",
        "italic",
        "underline",
        "ul",
        "ol",
        "link",
        "table",
        "inlineImage",
        "source",
      ],
      buttonsSM: ["paragraph", "h2", "h3", "lead", "bold", "italic", "ul", "ol", "table", "inlineImage", "source"],
      buttonsXS: ["paragraph", "h2", "lead", "bold", "ul", "ol", "table", "inlineImage", "source"],
      controls: {
        paragraph: {
          name: "paragraph",
          tooltip: "Paragraph",
          text: "P",
          exec: function (view) {
            view.execCommand("formatBlock", false, "p");
            view.synchronizeValues();
          },
        },
        h2: buildControl("h2", "h2", "H2"),
        h3: buildControl("h3", "h3", "H3"),
        h4: buildControl("h4", "h4", "H4"),
        lead: {
          name: "lead",
          tooltip: "Lead paragraph",
          text: "Lead",
          exec: function (view) {
            const selectedHtml = (view.s.html || "").trim();
            const content = selectedHtml || "Lead paragraph";
            view.s.insertHTML('<p class="article__lead">' + content + "</p>");
            view.synchronizeValues();
          },
        },
        inlineImage: {
          name: "inlineImage",
          tooltip: "Insert inline image",
          text: "Img",
          exec: function (view) {
            openInlineImageModal(view);
          },
        },
      },
      events: {
        change: function () {
          editor.synchronizeValues();
        },
        blur: function () {
          editor.synchronizeValues();
        },
      },
    });

    editors.set(textarea, editor);
    applyEditorPreviewClasses(editor);
    applyEditorTheme(editor);
  }

  function initEditors() {
    document.querySelectorAll("textarea[data-editor-role='article-body-html']").forEach(createEditor);
  }

  function bootstrapEditors() {
    registerThemeSync();
    initEditors();
    syncAllEditorsTheme();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bootstrapEditors);
  } else {
    bootstrapEditors();
  }
})();
