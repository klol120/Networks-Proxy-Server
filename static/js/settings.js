window.addEventListener('DOMContentLoaded', () => {
  const api = window.ProxyAdmin;
  const form = document.getElementById('settings-form');
  const cacheTimeout = document.getElementById('cache-timeout');
  const whitelistToggle = document.getElementById('settings-whitelist-toggle');
  const refreshButton = document.getElementById('settings-refresh-button');

  async function loadSettings() {
    try {
      const config = await api.fetchJSON('/api/config');
      cacheTimeout.value = config.cache_timeout || 0;
      whitelistToggle.checked = Boolean(config.use_whitelist);
    } catch (error) {
      alert('Unable to load settings: ' + error.message);
    }
  }

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    try {
      const currentConfig = await api.fetchJSON('/api/config');
      currentConfig.cache_timeout = Number(cacheTimeout.value || 0);
      currentConfig.use_whitelist = whitelistToggle.checked;

      await api.fetchJSON('/api/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(currentConfig)
      });
      await loadSettings();
      alert('Settings saved.');
    } catch (error) {
      alert('Unable to save settings: ' + error.message);
    }
  });

  refreshButton.addEventListener('click', loadSettings);
  loadSettings();
});
