// Alpine.js Store for Dark Mode
document.addEventListener('alpine:init', () => {
  Alpine.store('theme', {
    dark: localStorage.getItem('theme') === 'dark' ||
          (!('theme' in localStorage) && window.matchMedia('(prefers-color-scheme: dark)').matches),
    toggle() {
      this.dark = !this.dark;
      localStorage.setItem('theme', this.dark ? 'dark' : 'light');
      this.apply();
    },
    init() {
      this.apply();
    },
    apply() {
      if (this.dark) {
        document.documentElement.classList.add('dark');
      } else {
        document.documentElement.classList.remove('dark');
      }
    }
  });

  Alpine.store('theme').init();
});

function _csrfToken() {
  const meta = document.querySelector('meta[name="csrf-token"]');
  return meta ? meta.getAttribute('content') : '';
}

function togglePanel(id) {
  const el = document.getElementById(id);
  if (!el) return;
  const isHidden = el.classList.contains('hidden');
  if (isHidden) {
    el.classList.remove('hidden');
    el.classList.add('flex');
  } else {
    el.classList.add('hidden');
    el.classList.remove('flex');
  }
}

function toggleChat() {
  const inbox = document.getElementById('inbox-panel');
  if (inbox && !inbox.classList.contains('hidden')) {
    inbox.classList.add('hidden');
    inbox.classList.remove('flex');
  }
  togglePanel('chat-window');
  const messages = document.getElementById('chat-messages');
  if (messages) messages.scrollTop = messages.scrollHeight;
}

function toggleInbox() {
  const chat = document.getElementById('chat-window');
  if (chat && !chat.classList.contains('hidden')) {
    chat.classList.add('hidden');
    chat.classList.remove('flex');
  }
  togglePanel('inbox-panel');
}

function appendChat(html, className, asText) {
  const messagesContainer = document.getElementById('chat-messages');
  if (!messagesContainer) return null;
  const el = document.createElement('div');
  el.className = className;
  if (asText) el.innerText = html;
  else el.innerHTML = html;
  messagesContainer.appendChild(el);
  messagesContainer.scrollTop = messagesContainer.scrollHeight;
  return el;
}

function sendToAI() {
  const input = document.getElementById('ai-input');
  const messagesContainer = document.getElementById('chat-messages');
  if (!input || !messagesContainer) return;
  const userVal = input.value.trim();
  if (!userVal) return;

  appendChat(userVal, 'bg-brand-600 text-white p-3 rounded-2xl rounded-tl-sm max-w-[85%] self-end shadow-sm', true);
  input.value = '';

  const typingMsg = appendChat(
    '<i class="fa-solid fa-circle-notch fa-spin"></i> در حال پردازش...',
    'bg-white dark:bg-slate-800 p-3 rounded-2xl rounded-tr-sm border border-slate-100 dark:border-slate-700 shadow-sm text-slate-500 dark:text-slate-400 max-w-[85%] self-start',
    false
  );

  fetch('/assistant/ask', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-CSRFToken': _csrfToken(),
    },
    body: JSON.stringify({ q: userVal }),
  })
    .then((res) => res.json())
    .then((data) => {
      if (typingMsg) typingMsg.remove();
      const answer = (data && data.answer) ? data.answer : 'پاسخی دریافت نشد.';
      let html = answer.replace(/</g, '&lt;').replace(/>/g, '&gt;');
      if (data && data.url && data.cta) {
        const href = String(data.url).replace(/"/g, '');
        const cta = String(data.cta).replace(/</g, '&lt;');
        html += `<br><a href="${href}" class="inline-block mt-2 text-xs font-bold text-brand-600">${cta}</a>`;
      }
      appendChat(
        html,
        'bg-white dark:bg-slate-800 p-3 rounded-2xl rounded-tr-sm border border-slate-100 dark:border-slate-700 shadow-sm text-slate-700 dark:text-slate-200 max-w-[85%] self-start',
        false
      );
    })
    .catch(() => {
      if (typingMsg) typingMsg.remove();
      appendChat(
        'ارتباط با دستیار برقرار نشد. بعداً دوباره تلاش کنید.',
        'bg-white dark:bg-slate-800 p-3 rounded-2xl rounded-tr-sm border border-slate-100 dark:border-slate-700 shadow-sm text-slate-700 dark:text-slate-200 max-w-[85%] self-start',
        true
      );
    });
}
