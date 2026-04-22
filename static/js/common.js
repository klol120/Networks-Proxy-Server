(function () {
  function escapeHtml(value) {
    return String(value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function formatTimestamp(value) {
    if (!value) {
      return '—';
    }

    const date = new Date(value);
    if (Number.isNaN(date.getTime())) {
      return String(value);
    }

    return new Intl.DateTimeFormat(undefined, {
      dateStyle: 'medium',
      timeStyle: 'short'
    }).format(date);
  }

  function formatDuration(seconds) {
    const total = Math.max(0, Math.floor(Number(seconds) || 0));
    const days = Math.floor(total / 86400);
    const hours = Math.floor((total % 86400) / 3600);
    const minutes = Math.floor((total % 3600) / 60);
    const remainder = total % 60;
    const parts = [];

    if (days) parts.push(days + 'd');
    if (hours || parts.length) parts.push(hours + 'h');
    if (minutes || parts.length) parts.push(minutes + 'm');
    parts.push(remainder + 's');
    return parts.join(' ');
  }

  async function fetchJSON(url, options) {
    const response = await fetch(url, Object.assign({ headers: { Accept: 'application/json' } }, options || {}));
    const text = await response.text();
    let data = {};

    try {
      data = text ? JSON.parse(text) : {};
    } catch (error) {
      throw new Error('Invalid JSON response from ' + url);
    }

    if (!response.ok) {
      const message = data && data.error ? data.error : response.status + ' ' + response.statusText;
      throw new Error(message);
    }

    return data;
  }

  function setText(selector, value, root) {
    const node = (root || document).querySelector(selector);
    if (node) {
      node.textContent = value;
    }
    return node;
  }

  function renderEmptyState(message) {
    return '<li class="empty-state">' + escapeHtml(message) + '</li>';
  }

  window.ProxyAdmin = {
    escapeHtml: escapeHtml,
    formatTimestamp: formatTimestamp,
    formatDuration: formatDuration,
    fetchJSON: fetchJSON,
    setText: setText,
    renderEmptyState: renderEmptyState
  };
})();
