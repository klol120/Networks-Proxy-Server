window.addEventListener('DOMContentLoaded', () => {
  const api = window.ProxyAdmin;
  const tbody = document.getElementById('cache-table-body');
  const refreshButton = document.getElementById('refresh-cache-button');
  const clearButton = document.getElementById('clear-cache-button');
  const entryCount = document.getElementById('cache-entry-count');
  const validCount = document.getElementById('cache-valid-count');
  const expiredCount = document.getElementById('cache-expired-count');
  const timeoutValue = document.getElementById('cache-timeout-value');
  const lastUpdated = document.getElementById('cache-last-updated');

  function renderRows(entries) {
    if (!entries.length) {
      tbody.innerHTML = '<tr><td colspan="4" class="empty-state">No cache entries found.</td></tr>';
      return;
    }

    tbody.innerHTML = entries.map((entry) => {
      const statusClass = entry.expired ? 'cache-status-expired' : 'cache-status-valid';
      const statusText = entry.expired ? 'Expired' : 'Valid';
      return [
        '<tr>',
        '<td>' + api.escapeHtml(entry.url || '') + '</td>',
        '<td>' + api.escapeHtml(api.formatTimestamp(entry.cached_at ? entry.cached_at * 1000 : entry.cached_at)) + '</td>',
        '<td>' + api.escapeHtml(api.formatTimestamp(entry.expires ? entry.expires * 1000 : entry.expires)) + '</td>',
        '<td class="' + statusClass + '">' + statusText + '</td>',
        '</tr>'
      ].join('');
    }).join('');
  }

  async function refreshCache() {
    try {
      const [entries, config] = await Promise.all([
        api.fetchJSON('/api/cache'),
        api.fetchJSON('/api/config')
      ]);

      const sortedEntries = entries.slice().sort((a, b) => (b.cached_at || 0) - (a.cached_at || 0));
      const validEntries = sortedEntries.filter((entry) => !entry.expired);
      const expiredEntries = sortedEntries.length - validEntries.length;

      renderRows(sortedEntries);
      entryCount.textContent = String(sortedEntries.length);
      validCount.textContent = String(validEntries.length);
      expiredCount.textContent = String(expiredEntries);
      timeoutValue.textContent = api.formatDuration(config.cache_timeout || 0);
      lastUpdated.textContent = 'Updated ' + new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    } catch (error) {
      tbody.innerHTML = '<tr><td colspan="4" class="empty-state">Unable to load cache entries: ' + api.escapeHtml(error.message) + '</td></tr>';
    }
  }

  refreshButton.addEventListener('click', refreshCache);
  clearButton.addEventListener('click', async () => {
    if (!confirm('Clear all cached responses?')) {
      return;
    }

    try {
      await api.fetchJSON('/api/cache/clear');
      await refreshCache();
    } catch (error) {
      alert('Failed to clear cache: ' + error.message);
    }
  });

  refreshCache();
  setInterval(refreshCache, 10000);
});
