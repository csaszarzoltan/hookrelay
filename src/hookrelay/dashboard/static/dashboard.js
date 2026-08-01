// Hookrelay Dashboard: resilient live updates and workflow controls.
(function () {
    'use strict';
    const liveFeed = document.getElementById('live-feed');
    const liveBody = document.getElementById('live-feed-body');
    const statusNode = document.getElementById('connection-status');
    const pauseButton = document.getElementById('pause-live');
    const totalNode = document.getElementById('total-count');
    let socket = null;
    let reconnectAttempts = 0;
    let reconnectTimer = null;
    let paused = false;
    let latestCursor = parseInt(window.sessionStorage.getItem('hookrelayEventCursor') || '0', 10);
    const bufferedRequests = [];
    const maxRows = 50;

    function setStatus(state, label) {
        if (!statusNode) return;
        statusNode.className = 'connection-status ' + state;
        statusNode.textContent = label;
    }
    function insertLiveRequest(request) {
        if (!liveBody || !request || !request.request_id) return;
        const existing = Array.from(liveBody.rows).find(function (row) {
            return row.dataset.requestId === request.request_id;
        });
        if (existing) existing.remove();
        const row = document.createElement('tr');
        row.dataset.requestId = request.request_id;
        const values = [request.received_at ? request.received_at.slice(-12) : '', request.method, request.channel, request.path, request.source_ip];
        values.forEach(function (value, index) {
            const cell = document.createElement('td');
            if (index === 1) {
                const badge = document.createElement('span');
                badge.className = 'method method-' + String(value || '').toLowerCase();
                badge.textContent = value || '';
                cell.appendChild(badge);
            } else cell.textContent = value || '';
            row.appendChild(cell);
        });
        const idCell = document.createElement('td');
        const link = document.createElement('a');
        link.className = 'req-link';
        link.href = '/dashboard/inspect/' + encodeURIComponent(request.request_id);
        link.textContent = request.request_id.slice(0, 12);
        idCell.appendChild(link);
        row.appendChild(idCell);
        liveBody.prepend(row);
        while (liveBody.rows.length > maxRows) liveBody.deleteRow(liveBody.rows.length - 1);
        const empty = document.getElementById('live-empty-state');
        if (empty) empty.remove();
        if (totalNode) totalNode.textContent = String((parseInt(totalNode.textContent, 10) || 0) + 1);
    }
    function receiveRequest(request) {
        if (paused) {
            bufferedRequests.push(request);
            pauseButton.textContent = 'Resume updates (' + bufferedRequests.length + ')';
        } else insertLiveRequest(request);
    }
    function connectLiveFeed() {
        if (!liveFeed) return;
        clearTimeout(reconnectTimer);
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = protocol + '//' + window.location.host + '/dashboard/ws/live';
        setStatus('reconnecting', reconnectAttempts ? 'Reconnecting…' : 'Connecting…');
        socket = new WebSocket(wsUrl);
        socket.onopen = function () {
            reconnectAttempts = 0;
            setStatus('connected', 'Live connected');
            fetch('/api/events?after_cursor=' + latestCursor + '&event_type=webhook.received')
                .then(function (response) { return response.ok ? response.json() : { items: [] }; })
                .then(function (payload) {
                    (payload.items || []).forEach(function (event) {
                        receiveRequest(event.data);
                        latestCursor = Math.max(latestCursor, event.cursor || 0);
                    });
                    window.sessionStorage.setItem('hookrelayEventCursor', String(latestCursor));
                });
        };
        socket.onmessage = function (event) {
            let message;
            try { message = JSON.parse(event.data); } catch (_) { return; }
            if (message.type === 'webhook' || message.event_type === 'webhook.received') {
                receiveRequest(message.data || message);
                latestCursor = Math.max(latestCursor, message.cursor || 0);
                window.sessionStorage.setItem('hookrelayEventCursor', String(latestCursor));
            }
        };
        socket.onerror = function () { socket.close(); };
        socket.onclose = function () {
            setStatus('disconnected', 'Disconnected');
            reconnectAttempts += 1;
            const delay = Math.min(30000, 1000 * Math.pow(2, Math.min(reconnectAttempts, 5)));
            reconnectTimer = setTimeout(connectLiveFeed, delay);
        };
    }
    if (pauseButton) pauseButton.addEventListener('click', function () {
        paused = !paused;
        pauseButton.setAttribute('aria-pressed', String(paused));
        if (paused) pauseButton.textContent = 'Resume updates';
        else {
            bufferedRequests.splice(0).reverse().forEach(insertLiveRequest);
            pauseButton.textContent = 'Pause updates';
        }
    });
    connectLiveFeed();

    document.querySelectorAll('.validation-error .error-header').forEach(function (header) {
        header.addEventListener('click', function () {
            const expanded = header.getAttribute('aria-expanded') === 'true';
            header.setAttribute('aria-expanded', String(!expanded));
            header.parentElement.classList.toggle('expanded', !expanded);
        });
    });

    const replayForm = document.getElementById('replay-form');
    if (replayForm) window.replayRequest = function () {
        const result = document.getElementById('replay-result');
        const requestId = window.location.pathname.split('/').pop();
        const target = document.getElementById('target-url').value.trim();
        fetch('/api/replay/' + encodeURIComponent(requestId), {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ target: target || undefined })
        }).then(async function (response) {
            const payload = await response.json().catch(function () { return {}; });
            if (!response.ok) throw new Error(payload.error || 'Replay failed');
            result.className = 'success';
            result.textContent = 'Replay sent on channel ' + payload.channel + '.';
        }).catch(function (error) { result.className = 'error'; result.textContent = error.message; });
        result.style.display = 'block';
        return false;
    };

    const savedView = document.getElementById('saved-view');
    if (savedView) savedView.addEventListener('change', function () {
        if (savedView.value) window.location.assign('/dashboard/history?view=' + encodeURIComponent(savedView.value));
    });
    const saveView = document.getElementById('save-view');
    if (saveView) saveView.addEventListener('click', function () {
        const name = window.prompt('Name this request view:');
        if (!name) return;
        const filters = {};
        new FormData(document.getElementById('history-filter-form')).forEach(function (value, key) { if (value) filters[key] = value; });
        fetch('/api/request-views', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name: name, filters: filters }) })
            .then(async function (response) { const payload = await response.json(); if (!response.ok) throw new Error(payload.error); window.location.assign('/dashboard/history?view=' + payload.view_id); })
            .catch(function (error) { document.getElementById('view-result').textContent = error.message; });
    });
    const deleteView = document.getElementById('delete-view');
    if (deleteView) deleteView.addEventListener('click', function () {
        if (!window.confirm('Delete this saved view?')) return;
        fetch('/api/request-views/' + encodeURIComponent(deleteView.dataset.viewId), { method: 'DELETE' })
            .then(function (response) { if (!response.ok) throw new Error('Delete failed'); window.location.assign('/dashboard/history'); })
            .catch(function (error) { document.getElementById('view-result').textContent = error.message; });
    });

    const saveRetention = document.getElementById('save-retention');
    const purgeNow = document.getElementById('purge-now');
    const retentionResult = document.getElementById('retention-result');
    if (saveRetention) saveRetention.addEventListener('click', function () {
        const days = parseInt(document.getElementById('retention-days').value, 10);
        fetch('/api/settings/retention', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ days: days }) })
            .then(async function (response) { const payload = await response.json(); if (!response.ok) throw new Error(payload.error); retentionResult.textContent = 'Retention saved: ' + payload.days + ' days.'; })
            .catch(function (error) { retentionResult.textContent = error.message; });
    });
    if (purgeNow) purgeNow.addEventListener('click', function () {
        if (!window.confirm('Delete expired requests now?')) return;
        fetch('/api/settings/retention/purge', { method: 'POST' })
            .then(function (response) { return response.json(); })
            .then(function (payload) { retentionResult.textContent = 'Deleted ' + payload.deleted + ' requests.'; });
    });
    const saveBackupPolicy = document.getElementById('save-backup-policy');
    const runBackup = document.getElementById('run-backup');
    const backupResult = document.getElementById('backup-result');
    if (saveBackupPolicy) saveBackupPolicy.addEventListener('click', function () {
        const payload = {
            enabled: document.getElementById('backup-enabled').checked,
            interval_hours: parseInt(document.getElementById('backup-interval').value, 10),
            keep_last: parseInt(document.getElementById('backup-keep-last').value, 10)
        };
        fetch('/api/data/backup-policy', {
            method: 'PUT', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        }).then(async function (response) {
            const data = await response.json();
            if (!response.ok) throw new Error(data.error || 'Could not save backup policy');
            backupResult.textContent = 'Backup policy saved.';
        }).catch(function (error) { backupResult.textContent = error.message; });
    });
    if (runBackup) runBackup.addEventListener('click', function () {
        runBackup.disabled = true;
        backupResult.textContent = 'Creating verified backup…';
        fetch('/api/data/backups/run', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ force: true })
        }).then(async function (response) {
            const data = await response.json();
            if (!response.ok) throw new Error(data.error || data.status || 'Backup failed');
            backupResult.textContent = 'Backup complete. SHA-256: ' + data.sha256;
            document.getElementById('last-backup-at').textContent = data.completed_at;
        }).catch(function (error) {
            backupResult.textContent = error.message;
        }).finally(function () { runBackup.disabled = false; });
    });

    const backupCenterResult = document.getElementById('backup-center-result');
    const createFirstBackup = document.getElementById('create-first-backup');
    function runBackupFromCenter() {
        if (!backupCenterResult) return;
        backupCenterResult.textContent = 'Creating and verifying backup…';
        fetch('/api/data/backups/run', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ force: true })
        }).then(async function (response) {
            const data = await response.json();
            if (!response.ok) throw new Error(data.error || data.status || 'Backup failed');
            backupCenterResult.textContent = 'Backup complete. Reloading catalog…';
            window.location.assign('/dashboard/backups');
        }).catch(function (error) { backupCenterResult.textContent = error.message; });
    }
    if (createFirstBackup) createFirstBackup.addEventListener('click', runBackupFromCenter);
    document.querySelectorAll('[data-action="inspect-backup"]').forEach(function (button) {
        button.addEventListener('click', function () {
            const card = button.closest('.backup-card');
            const preview = card.querySelector('.backup-preview');
            const path = card.dataset.manifestPath;
            button.disabled = true;
            fetch('/api/data/backups/inspect?manifest_path=' + encodeURIComponent(path))
                .then(async function (response) {
                    const data = await response.json();
                    if (!response.ok) throw new Error(data.error || 'Inspection failed');
                    preview.textContent = JSON.stringify(data, null, 2);
                    preview.hidden = false;
                })
                .catch(function (error) { backupCenterResult.textContent = error.message; })
                .finally(function () { button.disabled = false; });
        });
    });
    document.querySelectorAll('[data-action="delete-backup"]').forEach(function (button) {
        button.addEventListener('click', function () {
            const card = button.closest('.backup-card');
            if (!window.confirm('Delete this backup manifest and database file?')) return;
            button.disabled = true;
            fetch('/api/data/backups?manifest_path=' + encodeURIComponent(card.dataset.manifestPath) + '&confirm=true', {
                method: 'DELETE'
            }).then(function (response) {
                if (!response.ok) return response.json().then(function (data) { throw new Error(data.error || 'Delete failed'); });
                card.remove();
                backupCenterResult.textContent = 'Backup bundle deleted.';
            }).catch(function (error) { backupCenterResult.textContent = error.message; })
              .finally(function () { button.disabled = false; });
        });
    });

})();
