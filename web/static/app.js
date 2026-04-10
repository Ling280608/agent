const chatEl = document.getElementById("chat");
const inputEl = document.getElementById("input");
const sendBtn = document.getElementById("sendBtn");
const newChatBtn = document.getElementById("newChatBtn");
const metaEl = document.getElementById("meta");
const sessionBadge = document.getElementById("sessionBadge");

let sessionId = null;
let busy = false;

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

function addMessage(role, text) {
  const msg = document.createElement("div");
  msg.className = "msg " + (role === "user" ? "msg--user" : "msg--assistant");

  const avatar = document.createElement("div");
  avatar.className = "msg__avatar";
  avatar.textContent = role === "user" ? "U" : "A";

  const bubble = document.createElement("div");
  bubble.className = "msg__bubble";
  bubble.textContent = text;

  msg.appendChild(avatar);
  msg.appendChild(bubble);
  chatEl.appendChild(msg);
  scrollToBottom();
  return { msg, bubble };
}

function addTyping() {
  const { msg, bubble } = addMessage("assistant", "思考中…");
  bubble.style.opacity = "0.8";
  bubble.dataset.typing = "1";
  return { msg, bubble };
}

function autoGrow() {
  inputEl.style.height = "auto";
  inputEl.style.height = Math.min(inputEl.scrollHeight, 160) + "px";
}

async function send() {
  const text = (inputEl.value || "").trim();
  if (!text || busy) return;

  busy = true;
  sendBtn.disabled = true;
  setMeta("Sending…", "ok");

  addMessage("user", text);
  inputEl.value = "";
  autoGrow();

  const typing = addTyping();

  try {
    const resp = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text, session_id: sessionId }),
    });

    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      throw new Error(err.detail || `HTTP ${resp.status}`);
    }

    const data = await resp.json();
    sessionId = data.session_id;
    sessionBadge.textContent = sessionId.slice(0, 8) + "…";

    typing.bubble.textContent = data.assistant || "";
    typing.bubble.style.opacity = "1";
    delete typing.bubble.dataset.typing;
    setMeta("Ready", "ok");
  } catch (e) {
    typing.bubble.textContent =
      "请求失败：\n" +
      String(e?.message || e) +
      "\n\n请检查后端是否启动、OPENAI_API_KEY/DASHSCOPE_API_KEY 是否设置。";
    typing.bubble.style.opacity = "1";
    setMeta("Error", "bad");
  } finally {
    busy = false;
    sendBtn.disabled = false;
  }
}

function resetChat() {
  sessionId = null;
  sessionBadge.textContent = "—";
  chatEl.innerHTML = "";
  addMessage("assistant", "新对话已开始。你可以直接提问。");
  setMeta("Ready", "ok");
}

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

