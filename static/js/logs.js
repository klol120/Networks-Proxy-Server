window.addEventListener('DOMContentLoaded', () => {
  const api = window.ProxyAdmin;
  const output = document.getElementById('log-output');
  const count = document.getElementById('log-count');
  const refreshButton = document.getElementById('refresh-logs-button');
  const autoRefresh = document.getElementById('auto-refresh-logs');

  async function refreshLogs() {
    try {
      const data = await api.fetchJSON('/api/logs');
      const lines = Array.isArray(data.lines) ? data.lines : [];
      output.textContent = lines.length ? lines.join('\n') : 'No log entries available yet.';
      count.textContent = lines.length + ' lines';
      output.scrollTop = output.scrollHeight;
    } catch (error) {
      output.textContent = 'Unable to load logs: ' + error.message;
      count.textContent = '0 lines';
    }
  }

  refreshButton.addEventListener('click', refreshLogs);
  refreshLogs();

  setInterval(() => {
    if (autoRefresh.checked) {
      refreshLogs();
    }
  }, 5000);
});
