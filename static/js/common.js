/**
 * common.js - FieldKit 全局通用工具函数
 * ==========================================
 * 封装全局 Toast 轻提示、文件上传基础交互、AJAX 请求等，
 * 所有工具页面均可直接调用，不依赖任何第三方库。
 */

// ============================================================
// Toast 轻提示系统
// ============================================================

const Toast = (() => {
    /** 获取或创建 Toast 容器 */
    function getContainer() {
        let el = document.getElementById("toast-container");
        if (!el) {
            el = document.createElement("div");
            el.id = "toast-container";
            el.className = "toast-container";
            document.body.appendChild(el);
        }
        return el;
    }

    /** Toast 图标映射 */
    const ICONS = {
        success: "&#10004;",
        error: "&#10008;",
        warning: "&#9888;",
        info: "&#8505;",
    };

    /**
     * 显示一条 Toast 消息
     * @param {string}  msg      - 消息文本（支持 HTML）
     * @param {string}  type     - 类型: success | error | warning | info
     * @param {number}  duration - 显示时长（毫秒），默认 3000
     */
    function show(msg, type = "info", duration = 3000) {
        const container = getContainer();

        const toast = document.createElement("div");
        toast.className = `toast toast-${type}`;
        toast.innerHTML = `
            <span class="toast-icon">${ICONS[type] || ICONS.info}</span>
            <span class="toast-msg">${msg}</span>
        `;

        container.appendChild(toast);

        // 动画结束后自动移除 DOM
        const removeAfterAnimation = () => {
            if (toast.parentNode) {
                toast.remove();
            }
        };
        toast.addEventListener("animationend", (e) => {
            if (e.animationName === "toastFadeOut") {
                removeAfterAnimation();
            }
        });
        // 兜底：duration 后强制移除
        setTimeout(removeAfterAnimation, duration + 350);
    }

    return {
        success: (msg, d) => show(msg, "success", d),
        error: (msg, d) => show(msg, "error", d),
        warning: (msg, d) => show(msg, "warning", d),
        info: (msg, d) => show(msg, "info", d),
    };
})();

// 别名：全局快捷调用
function showToast(msg, type, duration) {
    Toast[type] ? Toast[type](msg, duration) : Toast.info(msg, duration);
}


// ============================================================
// AJAX 请求封装
// ============================================================

const API = (() => {
    /**
     * 基础请求方法
     * @param {string}  url     - 请求地址
     * @param {object}  options - fetch 配置项
     * @returns {Promise<object>} - { ok, status, data, error }
     */
    async function request(url, options = {}) {
        const defaultHeaders = {};
        // 如果不是 FormData，默认加 JSON 头
        if (!(options.body instanceof FormData)) {
            defaultHeaders["Content-Type"] = "application/json";
        }

        try {
            const resp = await fetch(url, {
                headers: { ...defaultHeaders, ...options.headers },
                ...options,
            });

            const contentType = resp.headers.get("Content-Type") || "";

            let data;
            if (contentType.includes("application/json")) {
                data = await resp.json();
            } else if (contentType.includes("text/")) {
                data = await resp.text();
            } else {
                data = await resp.blob();  // 二进制文件（如下载 zip）
            }

            return {
                ok: resp.ok,
                status: resp.status,
                data,
                error: resp.ok ? null : (data?.detail || data?.message || `请求失败 (${resp.status})`),
            };
        } catch (err) {
            return {
                ok: false,
                status: 0,
                data: null,
                error: err.message || "网络异常，请检查网络连接",
            };
        }
    }

    return {
        get: (url, opts) => request(url, { method: "GET", ...opts }),
        post: (url, body, opts) =>
            request(url, {
                method: "POST",
                body: body instanceof FormData ? body : JSON.stringify(body),
                ...opts,
            }),
        put: (url, body, opts) =>
            request(url, {
                method: "PUT",
                body: JSON.stringify(body),
                ...opts,
            }),
        delete: (url, opts) => request(url, { method: "DELETE", ...opts }),
        /** 上传文件（FormData） */
        upload: (url, formData, opts) =>
            request(url, {
                method: "POST",
                body: formData,
                ...opts,
            }),
        /** 下载文件（返回 Blob 并触发浏览器下载） */
        download: async (url, filename, opts) => {
            const result = await request(url, { method: "GET", ...opts });
            if (result.ok && result.data instanceof Blob) {
                triggerDownload(result.data, filename);
                return { ok: true };
            }
            return { ok: false, error: result.error };
        },
    };
})();


// ============================================================
// 文件上传交互组件
// ============================================================

/**
 * 初始化文件上传拖拽区域
 *
 * 用法：
 *   const uploader = initUploadZone("#my-upload-zone", {
 *       accept: ".jpg,.png",
 *       multiple: true,
 *       onFilesSelected: (files) => { console.log(files); },
 *   });
 *
 * @param {string|HTMLElement} el         - 上传区域元素或选择器
 * @param {object}             options    - 配置项
 * @param {string}             options.accept        - 接受的文件类型（如 ".jpg,.png"）
 * @param {boolean}            options.multiple      - 是否多选，默认 true
 * @param {number}             options.maxFileSizeMB - 单个文件大小上限（MB）
 * @param {function}           options.onFilesSelected - 文件选中回调 (files: FileList) => void
 * @returns {{ destroy: function, getFiles: function, clearFiles: function }}
 */
function initUploadZone(el, options = {}) {
    const zone = typeof el === "string" ? document.querySelector(el) : el;
    if (!zone) {
        console.error("[initUploadZone] 未找到上传区域元素:", el);
        return { destroy() {}, getFiles() { return []; }, clearFiles() {} };
    }

    const {
        accept = "",
        multiple = true,
        maxFileSizeMB = 50,
        onFilesSelected = null,
    } = options;

    let selectedFiles = [];

    // 创建隐藏的 file input
    const input = document.createElement("input");
    input.type = "file";
    input.style.display = "none";
    input.accept = accept;
    input.multiple = multiple;
    zone.appendChild(input);

    // ---- 事件处理 ----
    function handleClick() {
        input.value = "";
        input.click();
    }

    function handleFileChange(e) {
        const files = Array.from(e.target.files || []);
        if (files.length === 0) return;

        // 文件大小校验
        const maxBytes = maxFileSizeMB * 1024 * 1024;
        const validFiles = [];
        for (const file of files) {
            if (file.size > maxBytes) {
                Toast.warning(
                    `文件 "${file.name}" 超过 ${maxFileSizeMB}MB 限制，已跳过`
                );
                continue;
            }
            validFiles.push(file);
        }

        if (validFiles.length > 0) {
            selectedFiles = [...selectedFiles, ...validFiles];
            if (typeof onFilesSelected === "function") {
                onFilesSelected(validFiles, selectedFiles);
            }
        }
    }

    function handleDragOver(e) {
        e.preventDefault();
        e.stopPropagation();
        zone.classList.add("drag-over");
    }

    function handleDragLeave(e) {
        e.preventDefault();
        e.stopPropagation();
        zone.classList.remove("drag-over");
    }

    function handleDrop(e) {
        e.preventDefault();
        e.stopPropagation();
        zone.classList.remove("drag-over");

        const dt = e.dataTransfer;
        if (dt && dt.files && dt.files.length > 0) {
            // 模拟 input change 处理
            const fakeEvent = { target: { files: dt.files } };
            handleFileChange(fakeEvent);
        }
    }

    // ---- 绑定事件 ----
    zone.addEventListener("click", handleClick);
    zone.addEventListener("dragover", handleDragOver);
    zone.addEventListener("dragleave", handleDragLeave);
    zone.addEventListener("drop", handleDrop);
    input.addEventListener("change", handleFileChange);

    // ---- 返回控制器 ----
    return {
        /** 销毁事件绑定 */
        destroy() {
            zone.removeEventListener("click", handleClick);
            zone.removeEventListener("dragover", handleDragOver);
            zone.removeEventListener("dragleave", handleDragLeave);
            zone.removeEventListener("drop", handleDrop);
            input.removeEventListener("change", handleFileChange);
            input.remove();
        },
        /** 获取当前已选文件列表 */
        getFiles() {
            return [...selectedFiles];
        },
        /** 清空已选文件 */
        clearFiles() {
            selectedFiles = [];
        },
        /** 移除指定文件 */
        removeFile(index) {
            if (index >= 0 && index < selectedFiles.length) {
                selectedFiles.splice(index, 1);
            }
        },
    };
}


// ============================================================
// 工具函数
// ============================================================

/**
 * 格式化文件大小为人类可读字符串
 * @param {number} bytes
 * @returns {string}
 */
function formatFileSize(bytes) {
    if (bytes < 1024) return bytes + " B";
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
    return (bytes / (1024 * 1024)).toFixed(1) + " MB";
}

/**
 * 渲染文件列表到指定容器
 * @param {HTMLElement} container - 容器 DOM
 * @param {File[]}      files     - 文件列表
 * @param {function}    onRemove  - 移除回调 (index) => void
 */
function renderFileList(container, files, onRemove) {
    if (!container) return;
    if (!files || files.length === 0) {
        container.innerHTML = "";
        return;
    }
    container.innerHTML = files
        .map(
            (f, i) => `
            <li class="file-item">
                <span class="file-item-name" title="${escapeHtml(f.name)}">${escapeHtml(f.name)}</span>
                <span class="file-item-size">${formatFileSize(f.size)}</span>
                <button class="file-item-remove" data-index="${i}" title="移除">&times;</button>
            </li>`
        )
        .join("");

    // 绑定移除按钮事件
    container.querySelectorAll(".file-item-remove").forEach((btn) => {
        btn.addEventListener("click", (e) => {
            e.stopPropagation();
            const idx = parseInt(btn.dataset.index, 10);
            if (typeof onRemove === "function") {
                onRemove(idx);
            }
        });
    });
}

/**
 * HTML 转义，防 XSS
 * @param {string} str
 * @returns {string}
 */
function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
}

/**
 * 触发浏览器下载
 * @param {Blob}   blob     - 文件 Blob
 * @param {string} filename - 下载文件名
 */
function triggerDownload(blob, filename) {
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
}

/**
 * 显示/隐藏 Loading 遮罩
 * @param {boolean} show - true 显示，false 隐藏
 * @param {string}  text - 加载提示文字
 */
function toggleLoading(show, text = "处理中...") {
    let overlay = document.getElementById("global-loading");
    if (show) {
        if (!overlay) {
            overlay = document.createElement("div");
            overlay.id = "global-loading";
            overlay.innerHTML = `
                <div class="loading-overlay">
                    <div class="loading-box">
                        <div class="spinner"></div>
                        <p class="loading-text">${escapeHtml(text)}</p>
                    </div>
                </div>`;
            document.body.appendChild(overlay);
        }
        overlay.style.display = "flex";
    } else if (overlay) {
        overlay.style.display = "none";
    }
}

// ---- Loading 样式注入 ----
(function injectLoadingStyle() {
    if (document.getElementById("loading-style")) return;
    const style = document.createElement("style");
    style.id = "loading-style";
    style.textContent = `
        .loading-overlay {
            position: fixed; inset: 0; z-index: 10000;
            display: flex; align-items: center; justify-content: center;
            background: rgba(0,0,0,0.35);
        }
        .loading-box {
            background: #fff; border-radius: 12px;
            padding: 32px 48px; text-align: center;
            box-shadow: 0 20px 60px rgba(0,0,0,0.15);
        }
        .loading-text {
            margin-top: 16px; font-size: 14px; color: #64748B;
        }
    `;
    document.head.appendChild(style);
})();


// ============================================================
// 页面初始化时的健康检查（可选）
// ============================================================
(async function initCheck() {
    const result = await API.get("/api/health");
    if (result.ok) {
        console.log("[FieldKit] 后端服务连接正常", result.data);
    } else {
        console.warn("[FieldKit] 后端服务连接失败:", result.error);
    }
})();
