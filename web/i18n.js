// English / Chinese for every Alche Home page.
//   _('English text')            -> the text in the current language
//   _('Hello {name}', {name})    -> with values filled in
//   I18N.apply()                 -> translate the static markup of the page
// The language is remembered in this browser and, once logged in, on the account (PUT /me/language).
(function () {
  const ZH = {
    // ---- shared ----
    'Log in': '登录', 'Log out': '退出登录', 'Email': '邮箱', 'Password': '密码', 'Send': '发送',
    'Refresh': '刷新', 'Messages': '消息', 'Assistant': '助手', 'Jobs': '工单', 'Profile': '资料',
    'Confirm': '确认', 'Discard': '放弃', 'Choose': '选择', 'Assign': '分配', 'Approve': '批准',
    'Suspend': '暂停', 'Accept': '接单', 'Decline': '拒绝', 'Closed': '已关闭', 'Today': '今天',
    'Yesterday': '昨天', 'You': '你', 'Request failed': '请求失败', 'Failed to fetch': '无法连接到服务器',
    'Please log in again.': '请重新登录。', 'Customer': '客户',
    // ---- customer profile and phone numbers ----
    'My profile': '我的资料', 'Your name': '你的姓名',
    'Home ZIP code (used for new requests, so we do not have to ask)':
      '家庭邮编（用于新请求，这样我们就不用再问）',
    'Phone number (confirmed with a code we text you)': '手机号码（通过短信验证码确认）',
    'Profile saved.': '资料已保存。',
    'Enter a 5-digit ZIP code.': '请输入 5 位邮编。',
    'Phone: {phone}': '电话：{phone}',
    'Current number: {phone}': '当前号码：{phone}',
    'Tap the number to call from your phone, or copy it.': '在手机上点按号码即可拨打，也可复制号码。',
    'Show my phone number to the customer once I accept their job':
      '接单后向客户显示我的手机号码',
    'Customers who book you see this number and can call you from their own phone. It is off by default.':
      '预订你的客户会看到这个号码，并可用自己的手机拨打。默认关闭。',
    // ---- customer app ----
    'Sign in with Google': '使用 Google 登录', 'Sign in with Facebook': '使用 Facebook 登录',
    'Password (10+ characters)': '密码（至少 10 位）', 'Register': '注册',
    'Create request': '创建请求', 'New request': '新请求',
    'Turn this chat into a repair request': '把这段对话变成维修请求',
    'Start over for a different problem': '为另一个问题重新开始',
    'Profile (GET /me)': '个人资料（GET /me）', 'Refresh token': '刷新令牌',
    'Photo': '照片', 'Attach photos (up to 3)': '添加照片（最多 3 张）',
    'Describe your home repair problem...': '描述你的家庭维修问题……',
    'Signed in': '已登录', 'Token refreshed': '令牌已刷新',
    'Session expired, please sign in again': '登录已过期，请重新登录',
    'Photo unavailable': '照片不可用', 'Attached photo': '已附照片', 'Remove': '移除',
    'Repair request #{n}': '维修请求 #{n}', 'Type': '类型', 'When': '时间', 'ZIP': '邮编',
    'Severity': '严重程度', 'Cancel request': '取消请求',
    'Cancel repair request #{n}?': '取消维修请求 #{n}？',
    'No handyman is available for ZIP {zip} right now. Our team has been alerted and will follow up here.':
      '邮编 {zip} 暂时没有可接单的师傅。我们的团队已收到提醒，会在这里跟进。',
    'Looking for a handyman. This can take a few minutes.': '正在为你寻找师傅，可能需要几分钟。',
    'Looking for a handyman.': '正在为你寻找师傅。',
    ' Asked {n} of up to {max}.': ' 已询问 {n} 位（最多 {max} 位）。',
    ' Waiting for a reply ({mins} min left before we ask the next one).':
      ' 等待回复（{mins} 分钟后将询问下一位）。',
    '{name} has accepted your request.': '{name} 已接受你的请求。',
    'A handyman has accepted your request.': '已有师傅接受了你的请求。',
    'Message {name}': '给 {name} 发消息', 'your handyman': '你的师傅',
    'Find me a handyman': '帮我找师傅', 'Choose a handyman': '选择师傅',
    'We ask the best match first, then the next, until someone accepts':
      '我们先问最匹配的师傅，再依次询问下一位，直到有人接单',
    'We could not find an available handyman for this request.': '没有找到可接这个请求的师傅。',
    '{name} · {rating} stars · {rate}% reply rate ': '{name} · {rating} 星 · 回复率 {rate}% ',
    'Best match': '最佳匹配',
    'No handyman covers ZIP {zip} right now. Tap Find me a handyman and our team will follow up.':
      '邮编 {zip} 暂时没有师傅覆盖。点“帮我找师傅”，我们的团队会跟进。',
    'Next: pick a handyman, or let us choose. If yours is busy we move on to the next best match.':
      '下一步：选择一位师傅，或让我们来选。如果你选的师傅没空，我们会继续询问下一位最匹配的。',
    'Working on your request...': '正在处理你的请求……',
    'Start a new request? This chat will be closed; existing repair requests are kept.':
      '开始新的请求？当前对话将被关闭，已有的维修请求会保留。',
    'Thinking...': '思考中……', 'Looking at your photo...': '正在查看你的照片……',
    'Please sign in again ({m})': '请重新登录（{m}）',
    'Signed in, but loading failed: {m}': '已登录，但加载失败：{m}',
    'No messages yet. Describe the problem or attach a photo.': '还没有消息。请描述问题或添加照片。',
    'You can attach up to {n} photos per message.': '每条消息最多添加 {n} 张照片。',
    '{name}: only JPEG, PNG or WebP photos.': '{name}：仅支持 JPEG、PNG 或 WebP 照片。',
    '{name} is larger than {n} MB.': '{name} 超过了 {n} MB。',
    'An account with that email already exists. Use your original sign-in method.':
      '该邮箱已有账号，请使用原来的登录方式。',
    'Sign-in failed: {m}': '登录失败：{m}',
    'Unexpected sign-in response: no tokens were returned': '登录响应异常：未返回令牌',
    // statuses, categories, urgency
    'PLUMBING': '水管', 'ELECTRICAL': '电工', 'HVAC': '暖通空调', 'CARPENTRY': '木工/地板',
    'APPLIANCE': '家电', 'GENERAL': '综合维修', 'EMERGENCY': '紧急', 'SAME_DAY': '今天',
    'FLEXIBLE': '时间灵活', 'LOW': '低', 'MEDIUM': '中', 'HIGH': '高',
    'DRAFT': '草稿', 'OPEN': '待派单', 'MATCHING': '匹配中', 'ASSIGNED': '已分配',
    'IN_PROGRESS': '进行中', 'COMPLETED': '已完成', 'RATED': '已评价', 'UNMATCHED': '未匹配',
    'CANCELLED': '已取消', 'PENDING': '待批准', 'APPROVED': '已批准',
    // ---- messages view ----
    'Select a conversation': '请选择一个对话',
    'Could not load your conversations ({m}).': '无法加载对话（{m}）。',
    'No conversations yet. Messaging opens once a handyman accepts a job.':
      '还没有对话。师傅接单后即可发消息。',
    'Job #{n} · {cat}': '工单 #{n} · {cat}', 'You: {text}': '你：{text}', 'No messages yet': '暂无消息',
    'Write a message...': '写消息……', 'This conversation is closed': '此对话已关闭',
    'Say hello to {name} below.': '在下方向 {name} 打个招呼。', 'Seen': '已读',
    'Could not open this conversation ({m}).': '无法打开此对话（{m}）。',
    'Job #{n} · {cat} · ZIP {zip} · {status}': '工单 #{n} · {cat} · 邮编 {zip} · {status}',
    'Translated from the original': '译自原文', 'Show original': '显示原文', 'Show translation': '显示译文',
    // ---- handyman app ----
    'Alche Home Pro': 'Alche Home 师傅端',
    'Log in with your handyman account. Need an account? Ask Alche Home ops for an invite link.':
      '请使用师傅账号登录。还没有账号？请向 Alche Home 运营人员索取邀请链接。',
    'Welcome! Choose a password (at least 10 characters) to finish setting up your account.':
      '欢迎！请设置密码（至少 10 位）以完成账号设置。',
    'New password': '新密码', 'Set password and log in': '设置密码并登录',
    'Job offers': '工单邀请', 'My jobs': '我的工单', 'Past jobs': '历史工单',
    'No open offers right now.': '目前没有待处理的邀请。', 'No active jobs.': '没有进行中的工单。',
    'Nothing yet.': '暂无。',
    'Ask for help with a job: likely causes, tools and parts, safety, or how to explain it to the customer.':
      '就某个工单寻求帮助：可能的原因、工具和配件、安全注意事项，或如何向客户解释。',
    'Ask the assistant about this job...': '就这个工单向助手提问……', 'Ask': '提问',
    'Draft a reply to the customer': '为客户起草回复',
    'Suggested message. Edit it, then send it from Messages.': '建议的消息。请修改后在“消息”里发送。',
    'Use in Messages': '用于消息',
    'You have no jobs to ask about yet.': '你还没有可咨询的工单。',
    'Ask anything about this job.': '可以随便问这个工单的任何问题。',
    'Messages open once you have accepted this job.': '接单后才能发消息。',
    'Display name (customers see this)': '显示名称（客户可见）', 'Your expertise': '你的专长',
    'Specialties (optional, separated by commas, e.g. hardwood floors, leak repair)':
      '特长（可选，用逗号分隔，例如：实木地板，漏水修理）',
    'ZIP codes you serve (separated by commas; the first is your home ZIP)':
      '你服务的邮编（用逗号分隔，第一个是你的主邮编）',
    'I am available for new jobs': '我可以接新工单', 'Save profile': '保存资料',
    'Phone number': '手机号码', 'Send code': '发送验证码', '6-digit code': '6 位验证码',
    'Pipes and plumbing': '水管和管道', 'Wood, flooring and carpentry': '木工、地板',
    'Electrical': '电工', 'Heating and cooling': '暖通空调', 'Appliances': '家电',
    'General repair': '综合维修',
    'Finish your profile (expertise and at least one ZIP code) so we can match you with jobs.':
      '请完善资料（专长和至少一个邮编），我们才能为你匹配工单。',
    'Your profile is waiting for approval by Alche Home. You will receive job offers once it is approved.':
      '你的资料正在等待 Alche Home 批准，批准后即可收到工单邀请。',
    'Profile approved. Changes apply to your next job offer.': '资料已批准，修改将在下一个工单邀请生效。',
    'Profile pending approval.': '资料待批准。',
    'Current number: {phone} (offers and messages are texted here when you are not in the app).':
      '当前号码：{phone}（你不在应用里时，邀请和消息会发到这个号码）。',
    'No phone number yet. Add one to get offers by SMS when you are not in the app.':
      '还没有手机号码。添加后，你不在应用里时可通过短信收到邀请。',
    'Profile saved.': '资料已保存。',
    'Please check your entries: ZIP codes need 5 digits and the name at least 2 characters.':
      '请检查输入：邮编必须是 5 位数字，名称至少 2 个字符。',
    'We texted a code to {to} (valid {mins} minutes).': '验证码已发送到 {to}（{mins} 分钟内有效）。',
    ' Local testing code: {code}': ' 本地测试验证码：{code}',
    'Enter the number like +16195550199.': '请按 +16195550199 的格式输入号码。',
    'Phone number confirmed.': '手机号码已确认。',
    'Wrong email or password.': '邮箱或密码不正确。',
    'This page is for handyman accounts.': '此页面仅供师傅账号使用。',
    'ZIP {zip} · Customer: {name}': '邮编 {zip} · 客户：{name}',
    ' · Severity: {s}': ' · 严重程度：{s}',
    'Offer expires in about {mins} min': '邀请约 {mins} 分钟后过期',
    'Messages ({n} new)': '消息（{n} 条新消息）', 'Ask the assistant': '问助手',
    'Job #{n} is yours. Say hello to the customer in Messages.': '工单 #{n} 已归你。请在“消息”里向客户打个招呼。',
    'Declined job #{n}.': '已拒绝工单 #{n}。',
    '({n}) New job offer - ': '（{n}）新的工单邀请 - ',
    // ---- ops page ----
    'Alche Home Ops': 'Alche Home 运营后台', 'Unmatched': '未匹配',
    'Waiting for a reply (matching)': '等待回复（匹配中）', 'Tickets': '工单',
    'Handymen': '师傅', 'Add a handyman': '添加师傅', 'Display name': '显示名称',
    'Create and get invite link': '创建并获取邀请链接',
    'No tickets here. Nice.': '这里没有工单，很好。', 'Choose handyman': '选择师傅',
    'Retry automatic dispatch': '重试自动派单', 'Nobody has this skill.': '没有人具备这项技能。',
    'Handyman': '师傅', 'Score': '分数', 'Covers ZIP': '覆盖邮编', 'Available': '可接单',
    'Rating': '评分', 'Response': '回复率', 'Earlier offer': '之前的邀请',
    'yes': '是', 'no': '否',
    '{status} · waiting {mins} min · {offers} offer(s) sent': '{status} · 已等待 {mins} 分钟 · 已发出 {offers} 次邀请',
    'Assign {name} to #{n}?{warn}': '把 #{n} 分配给 {name}？{warn}',
    ' They do not cover this ZIP or are unavailable.': ' 他们不覆盖这个邮编或当前不可接单。',
    '#{n} assigned to {name}.': '#{n} 已分配给 {name}。',
    'Dispatch restarted for #{n}.': '已为 #{n} 重新开始派单。',
    'Ticket is no longer UNMATCHED.': '该工单已不再是“未匹配”状态。',
    'This account is not an admin.': '此账号不是管理员。', 'Could not log in.': '无法登录。',
    'No handymen yet.': '还没有师傅。', 'New invite link': '新的邀请链接',
    'The profile needs expertise and a ZIP code first': '资料需要先填写专长和邮编',
    'Send this link to the handyman (works once, valid 7 days): {url}':
      '请把此链接发给师傅（只能使用一次，7 天内有效）：{url}',
    'Enter a valid email and a name of at least 2 characters.': '请输入有效的邮箱和至少 2 个字符的名称。',
    'no email': '无邮箱', 'no phone': '无手机号', 'has password': '已设置密码',
    'invite not used yet': '邀请尚未使用', 'available': '可接单', 'on break': '休息中',
    'Expertise: {skills} · ZIPs: {zips}': '专长：{skills} · 邮编：{zips}', 'none yet': '暂无',
    'Add the email and a display name': '请填写邮箱和显示名称',
    'Sign in with an admin account (see': '请使用管理员账号登录（参见',
    // ---- server errors ----
    'Invalid email or password': '邮箱或密码不正确',
    'Email already registered': '该邮箱已注册',
    'Not authenticated': '未登录', 'Token expired': '登录已过期', 'Invalid token': '登录无效',
    'Unknown user': '用户不存在', 'Ticket not found': '未找到该请求',
    'Conversation not found': '未找到该对话', 'This conversation is closed': '此对话已关闭',
    'Messaging opens once a handyman has accepted your request': '师傅接单后才能发消息',
    'That handyman is not available for this request': '这位师傅无法接这个请求',
    'One or more photos were not found': '有照片未找到',
    'Admins only': '仅限管理员', 'Handymen only': '仅限师傅',
    'This invite link is invalid or has expired': '此邀请链接无效或已过期',
    'That code is not right': '验证码不正确',
    'That code has expired. Request a new one.': '验证码已过期，请重新获取。',
    'Too many wrong codes. Request a new one.': '错误次数过多，请重新获取验证码。',
    'That phone number is already used by another account': '该手机号码已被其他账号使用',
    'Please wait a moment before requesting another code': '请稍等片刻再获取验证码',
    'Enter the phone number in international format, e.g. +16195550199':
      '请按国际格式输入手机号码，例如 +16195550199',
    'The profile needs expertise and at least one ZIP code first': '资料需要先填写专长和至少一个邮编',
    'That email already has an account': '该邮箱已有账号', 'Handyman not found': '未找到该师傅',
    'Job not found': '未找到该工单', 'Messages are for customers and handymen': '消息功能仅限客户和师傅',
  };

  // Codes the server sends (categories, statuses...) shown in plain English.
  const EN = {
    PLUMBING: 'Plumbing', ELECTRICAL: 'Electrical', HVAC: 'Heating / cooling', CARPENTRY: 'Carpentry',
    APPLIANCE: 'Appliance', GENERAL: 'General repair', EMERGENCY: 'Emergency', SAME_DAY: 'Today',
    FLEXIBLE: 'Flexible', LOW: 'Low', MEDIUM: 'Medium', HIGH: 'High', DRAFT: 'Draft', OPEN: 'Open',
    MATCHING: 'Matching', ASSIGNED: 'Assigned', IN_PROGRESS: 'In progress', COMPLETED: 'Completed',
    RATED: 'Rated', UNMATCHED: 'Unmatched', CANCELLED: 'Cancelled', PENDING: 'Pending',
    APPROVED: 'Approved', SENT: 'Sent', DECLINED: 'Declined', EXPIRED: 'Expired', ACCEPTED: 'Accepted',
  };
  Object.assign(ZH, { SENT: '已发送', DECLINED: '已拒绝', EXPIRED: '已过期', ACCEPTED: '已接单' });

  const PATTERNS = [
    [/^We are already working on request #(\d+)$/, '我们已经在处理请求 #$1'],
    [/^Ticket is (\w+); only UNMATCHED or MATCHING can be assigned$/, '工单状态为 $1，只有“未匹配”或“匹配中”的工单可以分配'],
    [/^Cannot move a ticket from (\w+) to (\w+)$/, '无法将工单从 $1 变为 $2'],
  ];

  const RTL_SAFE = ['SCRIPT', 'STYLE', 'TEXTAREA', 'CODE', 'PRE'];
  let lang = 'en';
  try {
    lang = localStorage.getItem('alche-lang') ||
      ((navigator.language || '').toLowerCase().startsWith('zh') ? 'zh' : 'en');
  } catch (e) { /* storage blocked: stay with English */ }

  // True once the language button was used in this browser (remembered, unlike the language
  // itself, which can also come from the account). An explicit choice wins over the account.
  let chose = false;
  try { chose = localStorage.getItem('alche-lang-chosen') === '1'; } catch (e) { /* ignore */ }
  const listeners = [];
  const originals = new WeakMap();   // text node or element -> its English text / attributes

  function fill(s, vars) {
    return vars ? s.replace(/\{(\w+)\}/g, (m, k) => (vars[k] !== undefined ? vars[k] : m)) : s;
  }
  function _(s, vars) {
    if (lang === 'zh' && ZH[s] !== undefined) return fill(ZH[s], vars);
    if (EN[s] !== undefined) return fill(EN[s], vars);
    return fill(s, vars);
  }
  function err(message) {
    if (lang !== 'zh' || !message) return message;
    if (ZH[message] !== undefined) return ZH[message];
    for (const [re, to] of PATTERNS) if (re.test(message)) return message.replace(re, to);
    return message;
  }
  function label(code) { return _(String(code)); }
  function status(code) { return _(String(code)); }

  function translateTextNode(node) {
    const base = originals.has(node) ? originals.get(node) : node.nodeValue;
    const trimmed = base.trim();
    if (!trimmed) return;
    if (!originals.has(node)) {
      if (ZH[trimmed] === undefined) return;       // not a known static string
      originals.set(node, base);
    }
    const out = lang === 'zh' ? ZH[trimmed] : trimmed;
    const lead = base.match(/^\s*/)[0], tail = base.match(/\s*$/)[0];
    node.nodeValue = lead + out + tail;
  }
  function translateAttrs(el) {
    for (const attr of ['placeholder', 'title']) {
      if (!el.hasAttribute(attr)) continue;
      let store = originals.get(el);
      if (!store) { store = {}; originals.set(el, store); }
      if (store[attr] === undefined) {
        const v = el.getAttribute(attr);
        if (ZH[v] === undefined) continue;
        store[attr] = v;
      }
      el.setAttribute(attr, lang === 'zh' ? ZH[store[attr]] : store[attr]);
    }
  }
  function apply(root) {
    root = root || document.body;
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
      acceptNode(n) {
        const p = n.parentElement;
        if (!p || RTL_SAFE.includes(p.tagName) || p.closest('[data-notranslate]')) {
          return NodeFilter.FILTER_REJECT;
        }
        return NodeFilter.FILTER_ACCEPT;
      }
    });
    const nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);
    nodes.forEach(translateTextNode);
    root.querySelectorAll('[placeholder],[title]').forEach(translateAttrs);
    document.documentElement.lang = lang === 'zh' ? 'zh-CN' : 'en';
    const btn = document.getElementById('langBtn');
    if (btn) btn.textContent = lang === 'zh' ? 'English' : '中文';
    if (!api.baseTitle) api.baseTitle = document.title;
    document.title = _(api.baseTitle);
  }

  function set(next, opts) {
    next = next === 'zh' ? 'zh' : 'en';
    if (next === lang && !(opts && opts.force)) return;
    lang = next;
    try { localStorage.setItem('alche-lang', lang); } catch (e) { /* ignore */ }
    apply();
    listeners.forEach(f => { try { f(lang); } catch (e) { console.error(e); } });
  }

  const api = {
    _, err, label, status, apply, set,
    lang: () => lang,
    onChange: f => listeners.push(f),
    // Set by each page: saves the choice on the account when someone is logged in.
    persist: null,
    // Called after login with the account's saved language, which wins over the browser's.
    adopt(accountLang) {
      if (accountLang !== 'en' && accountLang !== 'zh') return;
      // A language picked with the button in this browser keeps winning, and is saved on the account.
      if (chose && accountLang !== lang) { if (api.persist) api.persist(lang); return; }
      set(accountLang);
    },
  };
  window.I18N = api;
  window._ = _;

  document.addEventListener('DOMContentLoaded', () => {
    const btn = document.createElement('button');
    btn.id = 'langBtn';
    btn.type = 'button';
    btn.setAttribute('data-notranslate', '');
    btn.style.cssText = 'position:fixed;top:10px;right:10px;z-index:50;width:auto;margin:0;' +
      'padding:6px 12px;background:#fff;color:#2b5c8f;border:1px solid #2b5c8f;border-radius:6px;' +
      'font-weight:600;cursor:pointer;font-family:inherit';
    btn.onclick = () => {
      const next = lang === 'zh' ? 'en' : 'zh';
      chose = true;
      try { localStorage.setItem('alche-lang-chosen', '1'); } catch (e) { /* ignore */ }
      set(next);
      if (api.persist) api.persist(next);
    };
    document.body.appendChild(btn);
    apply();
  });
})();
