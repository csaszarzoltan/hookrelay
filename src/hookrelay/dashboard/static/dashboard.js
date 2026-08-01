// Hookrelay Dashboard — Live updates and interactions

(function () {
    'use strict';

    // ---- Live feed WebSocket ----
    const liveFeed = document.getElementById('live-feed');
    if (liveFeed) {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = protocol + '//' + window.location.host + '/dashboard/ws/live';
        const ws = new WebSocket(wsUrl);

        ws.onmessage = function (event) {
            const data = JSON.parse(event.data);
            if (data.type === 'webhook') {
                // Refresh the page to show new data
                setTimeout(function () { window.location.reload(); }, 500);
            }
        };

        ws.onclose = function () {
            // Reconnect after 3 seconds
            setTimeout(function () {
                new WebSocket(wsUrl);
            }, 3000);
        };
    }

    // ---- Expandable validation errors ----
    document.querySelectorAll('.validation-error .error-header').forEach(function (header) {
        header.addEventListener('click', function () {
            header.parentElement.classList.toggle('expanded');
        });
    });

    // ---- Replay form ----
    const replayForm = document.getElementById('replay-form');
    if (replayForm) {
        window.replayRequest = function () {
            const targetUrl = document.getElementById('target-url').value;
            const requestId = window.location.pathname.split('/').pop();
            const resultDiv = document.getElementById('replay-result');

            fetch('/api/replay/' + requestId, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ target: targetUrl || undefined }),
            })
                .then(function (response) {
                    if (response.ok) {
                        resultDiv.className = 'success';
                        resultDiv.textContent = 'Replay successful!';
                    } else {
                        resultDiv.className = 'error';
                        resultDiv.textContent = 'Replay failed: ' + response.statusText;
                    }
                    resultDiv.style.display = 'block';
                })
                .catch(function (err) {
                    resultDiv.className = 'error';
                    resultDiv.textContent = 'Error: ' + err.message;
                    resultDiv.style.display = 'block';
                });

            return false;
        };
    }
    // ---- Retention settings ----
    const saveRetention = document.getElementById('save-retention');
    const purgeNow = document.getElementById('purge-now');
    const retentionResult = document.getElementById('retention-result');
    function retentionDays() {
        return parseInt(document.getElementById('retention-days').value, 10);
    }
    if (saveRetention) {
        saveRetention.addEventListener('click', function () {
            fetch('/api/settings/retention', {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ days: retentionDays() })
            }).then(async function (response) {
                const payload = await response.json();
                if (!response.ok) throw new Error(payload.error || 'Could not save retention');
                retentionResult.textContent = 'Retention saved: ' + payload.days + ' days.';
            }).catch(function (error) { retentionResult.textContent = error.message; });
        });
    }
    if (purgeNow) {
        purgeNow.addEventListener('click', function () {
            if (!window.confirm('Delete all requests older than the configured retention period?')) return;
            purgeNow.disabled = true;
            fetch('/api/settings/retention/purge', { method: 'POST' })
                .then(async function (response) {
                    const payload = await response.json();
                    if (!response.ok) throw new Error(payload.error || 'Cleanup failed');
                    retentionResult.textContent = 'Cleanup complete. Deleted ' + payload.deleted + ' requests.';
                }).catch(function (error) {
                    retentionResult.textContent = error.message;
                }).finally(function () { purgeNow.disabled = false; });
        });
    }

})();
