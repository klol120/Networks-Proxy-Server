window.addEventListener('DOMContentLoaded', () => {
  const api = window.ProxyAdmin;
  const blacklistList = document.getElementById('blacklist-list');
  const whitelistList = document.getElementById('whitelist-list');
  const blacklistForm = document.getElementById('blacklist-form');
  const whitelistForm = document.getElementById('whitelist-form');
  const blacklistInput = document.getElementById('blacklist-input');
  const whitelistInput = document.getElementById('whitelist-input');
  const whitelistToggle = document.getElementById('whitelist-toggle');
  const whitelistModeValue = document.getElementById('whitelist-mode-value');
  const blacklistCount = document.getElementById('blacklist-count');
  const whitelistCount = document.getElementById('whitelist-count');

  function renderList(listNode, items, type) {
    if (!items.length) {
      listNode.innerHTML = '<li class="empty-state">No ' + type + ' entries yet.</li>';
      return;
    }

    listNode.innerHTML = items.map((item) => [
      '<li class="domain-item">',
      '<span><code>' + api.escapeHtml(item) + '</code></span>',
      '<span class="domain-actions">',
      '<button class="button button-secondary icon-button" type="button" data-action="remove" data-type="' + type + '" data-domain="' + api.escapeHtml(item) + '">Remove</button>',
      '</span>',
      '</li>'
    ].join('')).join('');
  }

  async function loadRules() {
    try {
      const config = await api.fetchJSON('/api/config');
      const blacklist = Array.isArray(config.blacklist) ? config.blacklist : [];
      const whitelist = Array.isArray(config.whitelist) ? config.whitelist : [];

      renderList(blacklistList, blacklist, 'blacklist');
      renderList(whitelistList, whitelist, 'whitelist');
      blacklistCount.textContent = String(blacklist.length);
      whitelistCount.textContent = String(whitelist.length);
      whitelistToggle.checked = Boolean(config.use_whitelist);
      whitelistModeValue.textContent = config.use_whitelist ? 'ON' : 'OFF';
    } catch (error) {
      blacklistList.innerHTML = '<li class="empty-state">Unable to load blacklist: ' + api.escapeHtml(error.message) + '</li>';
      whitelistList.innerHTML = '<li class="empty-state">Unable to load whitelist: ' + api.escapeHtml(error.message) + '</li>';
    }
  }

  async function submitRule(type, domain) {
    await api.fetchJSON('/api/' + type + '/add', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ domain: domain })
    });
    await loadRules();
  }

  blacklistForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    const domain = blacklistInput.value.trim();
    if (!domain) {
      return;
    }
    try {
      await submitRule('blacklist', domain);
      blacklistInput.value = '';
    } catch (error) {
      alert('Unable to add blacklist entry: ' + error.message);
    }
  });

  whitelistForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    const domain = whitelistInput.value.trim();
    if (!domain) {
      return;
    }
    try {
      await submitRule('whitelist', domain);
      whitelistInput.value = '';
    } catch (error) {
      alert('Unable to add whitelist entry: ' + error.message);
    }
  });

  whitelistToggle.addEventListener('change', async () => {
    try {
      const config = await api.fetchJSON('/api/config');
      config.use_whitelist = whitelistToggle.checked;
      await api.fetchJSON('/api/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(config)
      });
      await loadRules();
    } catch (error) {
      alert('Unable to update whitelist mode: ' + error.message);
      await loadRules();
    }
  });

  document.addEventListener('click', async (event) => {
    const button = event.target.closest('[data-action="remove"]');
    if (!button) {
      return;
    }

    const type = button.getAttribute('data-type');
    const domain = button.getAttribute('data-domain');
    try {
      await api.fetchJSON('/api/' + type + '/remove', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ domain: domain })
      });
      await loadRules();
    } catch (error) {
      alert('Unable to remove rule: ' + error.message);
    }
  });

  loadRules();
});
