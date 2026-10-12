// Messages view shared by the customer app and the handyman app.
// AlcheMessages.mount(root, { authed, onUnread }) -> { open(ticketId), refresh(), prefill(text), stop() }
// `authed(path, opts)` is the page's token-aware fetch helper. Everything from the server is put
// in with textContent, so message text is never interpreted as HTML.
// The composer (header, box, Send) is built once per conversation and never replaced while it is
// open, so polling cannot steal focus, drop half-typed text or interrupt an input method.
(function () {
  const el = (tag, cls, txt) => {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (txt != null) e.textContent = txt;
    return e;
  };
  const JSON_HEADERS = { 'Content-Type': 'application/json' };
  const time = d => new Date(d).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
  const dayLabel = d => {
    const x = new Date(d), n = new Date();
    if (x.toDateString() === n.toDateString()) return _('Today');
    const y = new Date(n); y.setDate(n.getDate() - 1);
    return x.toDateString() === y.toDateString() ? _('Yesterday')
      : x.toLocaleDateString(I18N.lang() === 'zh' ? 'zh-CN' : undefined);
  };
  const who = n => (n === 'Customer' || n === 'Handyman' ? _(n) : n);
  const snippet = t => (t.length > 60 ? t.slice(0, 57) + '...' : t);

  function mount(root, opts) {
    const authed = opts.authed;
    let current = null, listTimer = null, chatTimer = null, lastKey = '';
    let view = null;          // the open conversation's elements
    let listSig = '';         // what the conversation list currently shows
    let pendingText = '';
    root.classList.add('msgs');
    const list = el('div', 'msgs-list');
    const pane = el('div', 'msgs-pane');
    root.replaceChildren(list, pane);

    function showPlaceholder() {
      view = null;
      root.classList.remove('show-chat');
      pane.replaceChildren(el('div', 'msgs-empty', _('Select a conversation')));
    }
    showPlaceholder();

    function closeChat() {
      current = null; lastKey = '';
      clearInterval(chatTimer);
      showPlaceholder();
      refresh();
    }

    // ---- conversation list ----
    async function refresh() {
      let data;
      try { data = await authed('/threads'); } catch (e) {
        if (!list.children.length || list.querySelector('.msgs-empty')) {
          list.replaceChildren(el('div', 'msgs-empty', _('Could not load your conversations ({m}).', { m: e.message })));
        }
        return;
      }
      if (opts.onUnread) opts.onUnread(data.unread_total);
      const sig = JSON.stringify([current, I18N.lang(), data.threads]);
      if (sig === listSig) return;           // nothing changed: leave the DOM alone
      listSig = sig;
      if (!data.threads.length) {
        list.replaceChildren(el('div', 'msgs-empty',
          _('No conversations yet. Messaging opens once a handyman accepts a job.')));
        return;
      }
      list.replaceChildren(...data.threads.map(t => {
        const row = el('button', 'msgs-row' + (current === t.ticket_id ? ' active' : ''));
        row.type = 'button';
        const mid = el('span', 'mid');
        mid.append(
          el('strong', null, who(t.counterpart)),
          el('span', 'sub', _('Job #{n} · {cat}', { n: t.number, cat: _(t.category) })),
          el('span', 'last', t.last_body ? (t.last_from_me ? _('You: {text}', { text: snippet(t.last_body) }) : snippet(t.last_body)) : _('No messages yet')));
        const end = el('span', 'end');
        if (t.last_at) end.append(el('span', 'when', time(t.last_at)));
        if (t.unread) end.append(el('span', 'badge', String(t.unread)));
        if (!t.open) end.append(el('span', 'closed', _('Closed')));
        row.append(el('span', 'avatar', who(t.counterpart || '?').charAt(0).toUpperCase()), mid, end);
        row.onclick = () => open(t.ticket_id);
        return row;
      }));
    }

    // ---- open conversation ----
    function buildView(d) {
      const header = el('div', 'msgs-head');
      const back = el('button', 'back', '←');
      back.type = 'button';
      back.onclick = closeChat;
      const title = el('div', 'title');
      const name = el('strong'), sub = el('span', 'sub');
      const phone = el('a', 'phone');
      phone.style.display = 'none';
      title.append(name, sub, phone);
      header.append(back, title);
      const job = el('div', 'msgs-job');
      const body = el('div', 'msgs-body');
      const composer = el('div', 'msgs-composer');
      const input = el('textarea');
      input.rows = 1; input.maxLength = 500;
      const send = el('button', null, _('Send'));
      send.type = 'button';
      composer.append(input, send);
      view = { ticketId: d.ticket_id, name, sub, phone, job, body, input, send };

      const doSend = async () => {
        const text = input.value.trim();
        if (!text || send.disabled) return;
        send.disabled = true;
        try {
          const nd = await authed('/threads/' + d.ticket_id + '/messages',
            { method: 'POST', headers: JSON_HEADERS, body: JSON.stringify({ body: text }) });
          if (input.value.trim() === text) input.value = '';   // keep anything typed meanwhile
          lastKey = '';
          render(nd);
          refresh();
        } catch (e) { alert(e.message); }
        send.disabled = false;
        input.focus();
      };
      send.onclick = doSend;
      input.addEventListener('keydown', e => {
        // Enter confirms a candidate in input methods (Chinese, Japanese...): do not send then.
        if (e.key === 'Enter' && !e.shiftKey && !e.isComposing && e.keyCode !== 229) {
          e.preventDefault();
          doSend();
        }
      });
      pane.replaceChildren(header, job, body, composer);
      root.classList.add('show-chat');
      if (pendingText) { input.value = pendingText; pendingText = ''; }
    }

    function render(d) {
      if (!view || view.ticketId !== d.ticket_id || !pane.contains(view.input)) buildView(d);
      view.name.textContent = who(d.counterpart);
      view.sub.textContent = _('Job #{n} · {cat} · ZIP {zip} · {status}',
        { n: d.number, cat: _(d.category), zip: d.location_zip, status: _(d.status) });
      // The handyman's number appears only when they chose to share it (customer side).
      if (d.counterpart_phone) {
        view.phone.href = 'tel:' + d.counterpart_phone;
        view.phone.textContent = _('Phone: {phone}', { phone: d.counterpart_phone });
        view.phone.style.display = '';
      } else {
        view.phone.style.display = 'none';
      }
      view.job.textContent = d.issue_summary;
      view.job.setAttribute('data-notranslate', '');
      view.send.textContent = _('Send');
      view.input.disabled = !d.open;
      view.send.disabled = !d.open;
      view.input.placeholder = d.open ? _('Write a message...') : _('This conversation is closed');

      const body = view.body;
      const nearBottom = body.scrollHeight - body.scrollTop - body.clientHeight < 60;
      const nodes = [];
      let day = '', lastMine = -1;
      d.messages.forEach((m, i) => { if (m.mine) lastMine = i; });
      d.messages.forEach((m, i) => {
        const dl = dayLabel(m.created_at);
        if (dl !== day) { day = dl; nodes.push(el('div', 'day', dl)); }
        const b = el('div', 'bubble ' + (m.mine ? 'mine' : 'theirs'));
        b.setAttribute('data-notranslate', '');
        const text = el('span', null, m.body);
        b.append(text);
        if (m.translated && m.original) {   // the other person wrote in the other language
          const toggle = el('button', 'orig', _('Show original'));
          toggle.type = 'button';
          let showing = false;
          toggle.onclick = () => {
            showing = !showing;
            text.textContent = showing ? m.original : m.body;
            toggle.textContent = showing ? _('Show translation') : _('Show original');
          };
          b.append(toggle);
        }
        b.append(el('span', 'ts', time(m.created_at)));
        nodes.push(b);
        if (i === lastMine && d.other_read_at && new Date(d.other_read_at) >= new Date(m.created_at)) {
          nodes.push(el('div', 'seen', _('Seen')));
        }
      });
      if (!d.messages.length) nodes.push(el('div', 'msgs-empty', _('Say hello to {name} below.', { name: who(d.counterpart) })));
      body.replaceChildren(...nodes);
      if (nearBottom || !body.dataset.scrolled) { body.scrollTop = body.scrollHeight; body.dataset.scrolled = '1'; }
    }

    async function load(ticketId) {
      try {
        const d = await authed('/threads/' + ticketId + '/messages');
        if (current !== ticketId) return;      // the user moved on while this was loading
        const key = d.messages.length + ':' + (d.other_read_at || '') + ':' + d.status + ':' + (d.counterpart_phone || '');
        if (key !== lastKey || !view) { render(d); lastKey = key; }
      } catch (e) {
        // Never leave the pane blank without saying why; polling keeps retrying.
        if (!view) {
          const back = el('button', 'back', '←');
          back.type = 'button';
          back.onclick = closeChat;
          const head = el('div', 'msgs-head'); head.append(back);
          pane.replaceChildren(head, el('div', 'msgs-empty', _('Could not open this conversation ({m}).', { m: e.message })));
          root.classList.add('show-chat');
        }
      }
    }

    async function open(ticketId) {
      if (current === ticketId && view) { root.scrollIntoView({ block: 'start', behavior: 'smooth' }); return; }
      current = ticketId; lastKey = ''; listSig = '';
      view = null;
      clearInterval(chatTimer);
      root.scrollIntoView({ block: 'start', behavior: 'smooth' });  // keep the message box on screen
      await load(ticketId);
      chatTimer = setInterval(() => root.isConnected && current && load(current), 3000);
      refresh();
      if (view && !view.input.disabled) view.input.focus({ preventScroll: true });
    }

    refresh();
    listTimer = setInterval(() => root.isConnected && refresh(), 5000);
    return {
      open, refresh,
      prefill(text) {
        if (view) { view.input.value = text; view.input.focus(); } else pendingText = text;
      },
      // After a language change: redraw the list and the open conversation in the new language.
      relabel() { listSig = ''; lastKey = ''; refresh(); if (current) load(current); },
      stop() { clearInterval(listTimer); clearInterval(chatTimer); },
    };
  }

  window.AlcheMessages = { mount };
})();
