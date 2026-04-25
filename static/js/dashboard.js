window.addEventListener('DOMContentLoaded', () => {
  const api = window.ProxyAdmin;
  const statSelectors = {
    total_requests: '[data-stat="total_requests"]',
    cache_hits: '[data-stat="cache_hits"]',
    cache_misses: '[data-stat="cache_misses"]',
    blocked_requests: '[data-stat="blocked_requests"]',
    active_connections: '[data-stat="active_connections"]',
    errors: '[data-stat="errors"]'
  };

  async function refreshDashboard() {
    try {
      const [stats, logs, cacheEntries, config] = await Promise.all([
        api.fetchJSON('/api/stats'),
        api.fetchJSON('/api/logs'),
        api.fetchJSON('/api/cache'),
        api.fetchJSON('/api/config')
      ]);

      Object.entries(statSelectors).forEach(([key, selector]) => {
        const node = document.querySelector(selector);
        if (node) {
          node.textContent = Number(stats[key] || 0).toLocaleString();
        }
      });

      const trafficHintPanel = document.getElementById('traffic-hint-panel');
      if (trafficHintPanel) {
        trafficHintPanel.hidden = Number(stats.total_requests || 0) > 0;
      }

      const logLines = Array.isArray(logs.lines) ? logs.lines.slice(-12) : [];
      api.setText('#dashboard-logs', logLines.length ? logLines.join('\n') : 'No recent log entries.', document);

      const validEntries = cacheEntries.filter((entry) => !entry.expired).length;
      const expiredEntries = cacheEntries.length - validEntries;
      api.setText(
        '#dashboard-cache-summary',
        [
          'Entries: ' + cacheEntries.length,
          'Valid: ' + validEntries,
          'Expired: ' + expiredEntries,
          'Default timeout: ' + api.formatDuration(config.cache_timeout || 0)
        ].join('\n'),
        document
      );

      api.setText(
        '#dashboard-rule-summary',
        [
          'Blacklist entries: ' + ((config.blacklist || []).length),
          'Whitelist entries: ' + ((config.whitelist || []).length),
          'Whitelist mode: ' + ((config.use_whitelist && (config.whitelist || []).length ? 'ON' : config.use_whitelist ? 'ON' : 'OFF'))
        ].join('\n'),
        document
      );
    } catch (error) {
      api.setText('#dashboard-logs', 'Unable to load dashboard data: ' + error.message, document);
      api.setText('#dashboard-cache-summary', 'Unable to load cache summary.', document);
      api.setText('#dashboard-rule-summary', 'Unable to load filter summary.', document);
      const trafficHintPanel = document.getElementById('traffic-hint-panel');
      if (trafficHintPanel) {
        trafficHintPanel.hidden = true;
      }
    }
  }

  refreshDashboard();
  setInterval(refreshDashboard, 5000);
});
