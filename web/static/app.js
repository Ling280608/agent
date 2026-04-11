const chatEl = document.getElementById("chat");
const inputEl = document.getElementById("input");
const sendBtn = document.getElementById("sendBtn");
const newChatBtn = document.getElementById("newChatBtn");
const metaEl = document.getElementById("meta");
const sessionBadge = document.getElementById("sessionBadge");
const imageInput = document.getElementById("imageInput");
const imageBtn = document.getElementById("imageBtn");
const imagePreview = document.getElementById("imagePreview");

let sessionId = null;
let busy = false;
/** 当前进行中的流式请求，用于「新对话」时中止 */
let streamAbort = null;
/** 待发送的 data URL 列表（与后端 OpenAI 多模态格式一致） */
let pendingImages = [];

const MAX_IMAGES = 4;
const MAX_IMAGE_BYTES = 4 * 1024 * 1024;

function mdAvailable() {
  return typeof marked !== "undefined" && typeof DOMPurify !== "undefined";
}

if (typeof marked !== "undefined") {
  marked.setOptions({ gfm: true, breaks: true });
}

if (typeof DOMPurify !== "undefined") {
  DOMPurify.addHook("afterSanitizeAttributes", (node) => {
    if (node.tagName === "A" && node.getAttribute("target") === "_blank") {
      node.setAttribute("rel", "noopener noreferrer");
    }
  });
}

/** Markdown → 安全 HTML（库未加载时退化为纯文本换行） */
function renderMarkdown(md) {
  const src = md ?? "";
  if (!mdAvailable()) {
    const esc = src
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
    return esc.replace(/\n/g, "<br>");
  }
  try {
    const raw = marked.parse(src);
    return DOMPurify.sanitize(raw);
  } catch {
    const d = document.createElement("div");
    d.textContent = src;
    return d.innerHTML;
  }
}

function setBubbleMarkdown(bubble, md) {
  bubble.classList.add("msg__bubble--md");
  bubble.innerHTML = '<div class="md">' + renderMarkdown(md) + "</div>";
}

function setBubblePlain(bubble, text) {
  bubble.classList.remove("msg__bubble--md");
  bubble.textContent = text;
}

function setThinkMarkdown(el, md) {
  el.classList.add("msg__think-inner--md");
  el.innerHTML = '<div class="md">' + renderMarkdown(md) + "</div>";
}

function setThinkPlain(el, text) {
  el.classList.remove("msg__think-inner--md");
  el.textContent = text;
}

function setMeta(text, state = "ok") {
  metaEl.textContent = text;
  metaEl.prepend(makeDot(state));
}

function makeDot(state) {
  const dot = document.createElement("span");
  dot.className = "dot " + (state === "ok" ? "dot--ok" : "");
  return dot;
}

function scrollToBottom() {
  chatEl.scrollTop = chatEl.scrollHeight;
}

function readFileAsDataURL(file) {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(r.result);
    r.onerror = () => reject(new Error("读取图片失败"));
    r.readAsDataURL(file);
  });
}

/**
 * 与「附图」选择、粘贴共用：校验数量/大小后读成 data URL 并刷新预览。
 */
async function ingestImageFiles(files) {
  for (const file of Array.from(files || [])) {
    if (!file.type.startsWith("image/")) continue;
    if (pendingImages.length >= MAX_IMAGES) {
      setMeta("最多 " + MAX_IMAGES + " 张图", "bad");
      break;
    }
    if (file.size > MAX_IMAGE_BYTES) {
      setMeta("单张图片不超过 4MB", "bad");
      continue;
    }
    try {
      pendingImages.push(await readFileAsDataURL(file));
    } catch {
      setMeta("读取图片失败", "bad");
    }
  }
  renderImagePreview();
  if (pendingImages.length) setMeta("Ready", "ok");
}

function renderImagePreview() {
  imagePreview.innerHTML = "";
  pendingImages.forEach((url, i) => {
    const wrap = document.createElement("div");
    wrap.className = "composer__thumb-wrap";
    const img = document.createElement("img");
    img.src = url;
    img.className = "composer__thumb";
    img.alt = "";
    const rm = document.createElement("button");
    rm.type = "button";
    rm.className = "composer__thumb-remove";
    rm.setAttribute("aria-label", "移除图片");
    rm.textContent = "×";
    rm.addEventListener("click", () => {
      pendingImages.splice(i, 1);
      renderImagePreview();
    });
    wrap.appendChild(img);
    wrap.appendChild(rm);
    imagePreview.appendChild(wrap);
  });
}

/**
 * @param {"user"|"assistant"} role
 * @param {string} text
 * @param {string[]|undefined} imageUrls 用户消息可选：data:image/...;base64,... 用于展示与发给后端
 */
function addMessage(role, text, imageUrls) {
  const msg = document.createElement("div");
  msg.className = "msg " + (role === "user" ? "msg--user" : "msg--assistant");

  const avatar = document.createElement("div");
  avatar.className = "msg__avatar";
  avatar.textContent = role === "user" ? "U" : "A";

  const bubble = document.createElement("div");
  bubble.className = "msg__bubble";
  if (role === "assistant") {
    setBubbleMarkdown(bubble, text);
  } else {
    const urls = imageUrls && imageUrls.length ? imageUrls : null;
    if (urls) {
      const media = document.createElement("div");
      media.className = "msg__user-media";
      urls.forEach((url) => {
        const img = document.createElement("img");
        img.src = url;
        img.alt = "附图";
        img.className = "msg__user-img";
        media.appendChild(img);
      });
      bubble.appendChild(media);
    }
    if (text) {
      const te = document.createElement("div");
      te.className = "msg__user-text";
      te.textContent = text;
      bubble.appendChild(te);
    }
    if (!urls && !text) {
      bubble.textContent = "";
    }
  }

  msg.appendChild(avatar);
  msg.appendChild(bubble);
  chatEl.appendChild(msg);
  scrollToBottom();
  return { msg, bubble };
}

/** 助手流式占位：上方可折叠「思考过程」，下方为正文气泡 */
function addAssistantStreamShell() {
  const msg = document.createElement("div");
  msg.className = "msg msg--assistant";

  const avatar = document.createElement("div");
  avatar.className = "msg__avatar";
  avatar.textContent = "A";

  const body = document.createElement("div");
  body.className = "msg__body";

  const thinkDetails = document.createElement("details");
  thinkDetails.className = "msg__think";
  thinkDetails.hidden = true;
  const thinkSummary = document.createElement("summary");
  thinkSummary.textContent = "思考过程";
  const thinkInner = document.createElement("div");
  thinkInner.className = "msg__think-inner";
  thinkDetails.appendChild(thinkSummary);
  thinkDetails.appendChild(thinkInner);

  const bubble = document.createElement("div");
  bubble.className = "msg__bubble";
  bubble.textContent = "等待模型…";
  bubble.style.opacity = "0.85";
  bubble.dataset.typing = "1";
  bubble.setAttribute("aria-busy", "true");

  body.appendChild(thinkDetails);
  body.appendChild(bubble);
  msg.appendChild(avatar);
  msg.appendChild(body);
  chatEl.appendChild(msg);
  scrollToBottom();

  return { msg, bubble, thinkDetails, thinkInner };
}

/**
 * 解析后端 SSE（text/event-stream）：按空行分块，每块可含多行 data:。
 * 回调 onSession / onThinking / onToken / onDone / onError；返回正文累计、思考累计、是否 done。
 */
async function consumeChatSse(
  resp,
  { signal, onSession, onThinking, onToken, onDone, onError }
) {
  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let carry = "";
  let fullText = "";
  let fullThinking = "";
  let sawDone = false;

  while (true) {
    if (signal?.aborted) throw new DOMException("Aborted", "AbortError");
    const { done, value } = await reader.read();
    if (done) break;
    carry += decoder.decode(value, { stream: true });
    const chunks = carry.split("\n\n");
    carry = chunks.pop() || "";

    for (const block of chunks) {
      const dataPayload = block
        .split("\n")
        .filter((line) => line.startsWith("data:"))
        .map((line) => line.slice(5).replace(/^\s/, ""))
        .join("\n");
      if (!dataPayload) continue;

      let payload;
      try {
        payload = JSON.parse(dataPayload);
      } catch {
        continue;
      }

      if (payload.event === "session" && payload.session_id) {
        onSession?.(payload.session_id);
      } else if (payload.event === "thinking" && payload.text) {
        fullThinking += payload.text;
        onThinking?.(payload.text, fullThinking);
      } else if (payload.event === "token" && payload.text) {
        fullText += payload.text;
        onToken?.(payload.text, fullText);
      } else if (payload.event === "done") {
        sawDone = true;
        onDone?.();
      } else if (payload.event === "error") {
        onError?.(payload.detail || "流式输出出错");
      }
    }
  }

  return { fullText, fullThinking, sawDone };
}

function autoGrow() {
  inputEl.style.height = "auto";
  inputEl.style.height = Math.min(inputEl.scrollHeight, 160) + "px";
}

async function send() {
  const text = (inputEl.value || "").trim();
  const imgs = pendingImages.length ? [...pendingImages] : undefined;
  if ((!text && !imgs) || busy) return;

  streamAbort?.abort();
  streamAbort = new AbortController();
  const { signal } = streamAbort;

  busy = true;
  sendBtn.disabled = true;
  setMeta("正在连接…", "ok");

  addMessage("user", text, imgs);
  inputEl.value = "";
  autoGrow();
  pendingImages = [];
  renderImagePreview();

  const shell = addAssistantStreamShell();
  const { bubble, thinkDetails, thinkInner } = shell;

  try {
    const payload = { message: text, session_id: sessionId };
    if (imgs) payload.images = imgs;
    const resp = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      signal,
    });

    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      throw new Error(err.detail || `HTTP ${resp.status}`);
    }

    const ct = (resp.headers.get("content-type") || "").toLowerCase();
    if (!ct.includes("text/event-stream")) {
      throw new Error("期望 text/event-stream，实际为 " + (ct || "未知"));
    }

    let answerStarted = false;

    const { fullText, fullThinking, sawDone } = await consumeChatSse(resp, {
      signal,
      onSession: (id) => {
        sessionId = id;
        sessionBadge.textContent = id.slice(0, 8) + "…";
      },
      onThinking: (_piece, acc) => {
        thinkDetails.hidden = false;
        thinkDetails.open = true;
        setThinkMarkdown(thinkInner, acc);
        thinkInner.classList.add("msg__think-inner--live");
        setMeta("模型思考中…", "ok");
        scrollToBottom();
      },
      onToken: (_piece, acc) => {
        if (!answerStarted) {
          answerStarted = true;
          bubble.classList.add("msg__bubble--streaming");
          bubble.style.opacity = "1";
          setMeta("流式生成中…", "ok");
        }
        setBubbleMarkdown(bubble, acc);
        scrollToBottom();
      },
      onDone: () => {},
      onError: (detail) => {
        throw new Error(detail);
      },
    });

    thinkInner.classList.remove("msg__think-inner--live");
    if (fullThinking.trim()) {
      thinkDetails.open = false;
    } else {
      thinkDetails.hidden = true;
    }

    bubble.classList.remove("msg__bubble--streaming");
    delete bubble.dataset.typing;
    bubble.removeAttribute("aria-busy");

    if (!sawDone && fullText === "" && !fullThinking.trim()) {
      throw new Error("连接已结束，但未收到完整回复（未收到 done 且无内容）");
    }
    if (!sawDone && (fullText !== "" || fullThinking.trim())) {
      setMeta("已结束（未收到 done 事件）", "ok");
    } else {
      setMeta("Ready", "ok");
    }

    if (fullText === "" && sawDone) {
      setBubblePlain(
        bubble,
        fullThinking.trim()
          ? "（仅有思考过程，无正文；可展开「思考过程」查看）"
          : "（模型未返回可见文本）"
      );
    }
  } catch (e) {
    if (thinkInner) thinkInner.classList.remove("msg__think-inner--live");
    bubble.classList.remove("msg__bubble--streaming");
    delete bubble.dataset.typing;
    bubble.removeAttribute("aria-busy");

    if (e?.name === "AbortError") {
      setMeta("已取消", "ok");
      return;
    }

    setBubblePlain(
      bubble,
      "请求失败：\n" +
        String(e?.message || e) +
        "\n\n请检查后端是否启动、OPENAI_API_KEY/DASHSCOPE_API_KEY 是否设置。"
    );
    bubble.style.opacity = "1";
    setMeta("Error", "bad");
  } finally {
    busy = false;
    sendBtn.disabled = false;
    streamAbort = null;
  }
}

function resetChat() {
  streamAbort?.abort();
  streamAbort = null;
  sessionId = null;
  sessionBadge.textContent = "—";
  pendingImages = [];
  renderImagePreview();
  chatEl.innerHTML = "";
  addMessage("assistant", "新对话已开始。你可以直接提问。");
  setMeta("Ready", "ok");
}

/** 首屏 HTML 里写死的欢迎语 → 同样走 Markdown 渲染 */
function hydrateStaticWelcome() {
  const first = chatEl?.querySelector(".msg--assistant .msg__bubble");
  if (first && !first.classList.contains("msg__bubble--md")) {
    const t =
      first.textContent.trim() ||
      "你好，我已连接到后端 Agent。你可以问我任何问题。";
    setBubbleMarkdown(first, t);
  }
}

imageBtn.addEventListener("click", () => imageInput.click());

imageInput.addEventListener("change", async () => {
  const files = Array.from(imageInput.files || []);
  imageInput.value = "";
  await ingestImageFiles(files);
});

/**
 * 在输入框聚焦时 Ctrl+V：若剪贴板里是图片（截图、从浏览器/画图复制等），
 * 走与「附图」相同的入队逻辑；纯文字不传图片则不调 preventDefault，浏览器照常插入文字。
 */
inputEl.addEventListener("paste", async (e) => {
  const items = e.clipboardData?.items;
  if (!items?.length) return;
  const imageFiles = [];
  for (const item of items) {
    if (item.kind === "file" && item.type.startsWith("image/")) {
      const f = item.getAsFile();
      if (f) imageFiles.push(f);
    }
  }
  if (!imageFiles.length) return;
  e.preventDefault();
  await ingestImageFiles(imageFiles);
});

inputEl.addEventListener("input", autoGrow);
sendBtn.addEventListener("click", send);
newChatBtn.addEventListener("click", resetChat);

inputEl.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    send();
  }
});

autoGrow();
setMeta("Ready", "ok");
hydrateStaticWelcome();
