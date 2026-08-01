// Hookrelay Dashboard: resilient live updates, accessible state, and replay feedback.
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
    const bufferedRequests = [];
    const maxRows = 50;

    function text(value) {
        return value === null || value === undefined ? '' : String(value);
    }

    function setConnectionStatus(state, label) {
        if (!statusNode) return;
        statusNode.className = 'connection-status ' + state;
        statusNode.textContent = label;
    }

    function methodClass(method) {
        return 'method method-' + text(method || 'post').toLowerCase();
    }

    function insertLiveRequest(request) {
        if (!liveBody) {
            window.location.assign('/dashboard/');
            return;
        }
        if (!request || !request.request_id) return;
        const existing = liveBody.querySelector('[data-request-id="' + CSS.escape(request.request_id) + '"]');
        if (existing) existing.remove();

        const row = document.createElement('tr');
        row.dataset.requestId = request.request_id;
        const received = text(request.received_at);
        const values = [received ? received.slice(-12) : '', request.method, request.channel, request.path, request.source_ip];
        values.forEach(function (value, index) {
            const cell = document.createElement('td');
            if (index === 0) cell.className = 'time';
            if (index === 1) {
                const badge = document.createElement('span');
                badge.className = methodClass(value);
                badge.textContent = text(value);
                cell.appendChild(badge);
            } else {
                cell.textContent = text(value);
            }
            row.appendChild(cell);
        });
        const idCell = document.createElement('td');
        const link = document.createElement('a');
        link.className = 'req-link';
        link.href = '/dashboard/inspect/' + encodeURIComponent(request.request_id);
        link.textContent = request.request_id.slice(0, 12);
        link.setAttribute('aria-label', 'Inspect request ' + request.request_id);
        idCell.appendChild(link);
        row.appendChild(idCell);
        liveBody.prepend(row);
        while (liveBody.rows.length > maxRows) liveBody.deleteRow(liveBody.rows.length - 1);
        const empty = document.getElementById('live-empty-state');
        if (empty) empty.remove();
        if (totalNode) totalNode.textContent = String((parseInt(totalNode.textContent, 10) || 0) + 1);
    }

    function handleLiveRequest(request) {
        if (paused) {
            bufferedRequests.push(request);
            pauseButton.textContent = 'Resume updates (' + bufferedRequests.length + ')';
            return;
        }
        insertLiveRequest(request);
    }

    function connectLiveFeed() {
        if (!liveFeed) return;
        clearTimeout(reconnectTimer);
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = protocol + '//' + window.location.host + '/dashboard/ws/live';
        setConnectionStatus('reconnecting', reconnectAttempts ? 'Reconnecting…' : 'Connecting…');
        socket = new WebSocket(wsUrl);
        socket.onopen = function () {
            reconnectAttempts = 0;
            setConnectionStatus('connected', 'Live connected');
        };
        socket.onmessage = function (event) {
            let message;
            try { message = JSON.parse(event.data); } catch (_) { return; }
            if (message.type === 'webhook') handleLiveRequest(message.data || message);
        };
        socket.onerror = function () { socket.close(); };
        socket.onclose = function () {
            setConnectionStatus('disconnected', 'Disconnected');
            reconnectAttempts += 1;
            const delay = Math.min(30000, 1000 * Math.pow(2, Math.min(reconnectAttempts, 5)));
            reconnectTimer = setTimeout(connectLiveFeed, delay);
        };
    }

    if (pauseButton) {
        pauseButton.addEventListener('click', function () {
            paused = !paused;
            pauseButton.setAttribute('aria-pressed', String(paused));
            if (paused) {
                pauseButton.textContent = 'Resume updates';
            } else {
                bufferedRequests.splice(0).reverse().forEach(insertLiveRequest);
                pauseButton.textContent = 'Pause updates';
            }
        });
    }
    connectLiveFeed();

    document.querySelectorAll('.validation-error .error-header').forEach(function (header) {
        header.addEventListener('click', function () {
            const expanded = header.getAttribute('aria-expanded') === 'true';
            header.setAttribute('aria-expanded', String(!expanded));
            header.parentElement.classList.toggle('expanded', !expanded);
        });
    });

    const replayForm = document.getElementById('replay-form');
    if (replayForm) {
        window.replayRequest = function () {
            const targetUrl = document.getElementById('target-url').value.trim();
            const requestId = window.location.pathname.split('/').pop();
            const resultDiv = document.getElementById('replay-result');
            const submit = document.getElementById('replay-submit');
            submit.disabled = true;
            submit.textContent = 'Replaying…';
            resultDiv.className = 'pending';
            resultDiv.textContent = 'Replay in progress.';
            resultDiv.style.display = 'block';
            fetch('/api/replay/' + encodeURIComponent(requestId), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ target: targetUrl || undefined })
            }).then(async function (response) {
                const payload = await response.json().catch(function () { return {}; });
                if (!response.ok) throw new Error(payload.error || ('Replay failed with HTTP ' + response.status));
                resultDiv.className = 'success';
                resultDiv.textContent = 'Replay sent on channel ' + text(payload.channel) + '.';
            }).catch(function (error) {
                resultDiv.className = 'error';
                resultDiv.textContent = error.message;
            }).finally(function () {
                submit.disabled = false;
                submit.textContent = 'Replay now';
            });
            return false;
        };
    }
    const savedViewSelect = document.getElementById('saved-view');
    if (savedViewSelect) {
        savedViewSelect.addEventListener('change', function () {
            if (savedViewSelect.value) {
                window.location.assign('/dashboard/history?view=' + encodeURIComponent(savedViewSelect.value));
            }
        });
    }

    const saveViewButton = document.getElementById('save-view');
    if (saveViewButton) {
        saveViewButton.addEventListener('click', function () {
            const name = window.prompt('Name this request view:');
            if (!name) return;
            const params = new URLSearchParams(new FormData(document.getElementById('history-filter-form')));
            const filters = {};
            params.forEach(function (value, key) { if (value) filters[key] = value; });
            fetch('/api/request-views', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name: name, filters: filters })
            }).then(async function (response) {
                const payload = await response.json().catch(function () { return {}; });
                if (!response.ok) throw new Error(payload.error || 'Could not save view');
                window.location.assign('/dashboard/history?view=' + encodeURIComponent(payload.view_id));
            }).catch(function (error) {
                document.getElementById('view-result').textContent = error.message;
            });
        });
    }

    const deleteViewButton = document.getElementById('delete-view');
    if (deleteViewButton) {
        deleteViewButton.addEventListener('click', function () {
            if (!window.confirm('Delete this saved view? Stored requests will not be deleted.')) return;
            fetch('/api/request-views/' + encodeURIComponent(deleteViewButton.dataset.viewId), {
                method: 'DELETE'
            }).then(function (response) {
                if (!response.ok) throw new Error('Could not delete view');
                window.location.assign('/dashboard/history');
            }).catch(function (error) {
                document.getElementById('view-result').textContent = error.message;
            });
        });
    }

    const deleteButton = document.getElementById('delete-request');
    if (deleteButton) {
        deleteButton.addEventListener('click', function () {
            const requestId = deleteButton.dataset.requestId;
            if (!window.confirm('Permanently delete this stored request and its diagnostic history?')) return;
            deleteButton.disabled = true;
            fetch('/api/requests/' + encodeURIComponent(requestId) + '?confirm=true', {
                method: 'DELETE'
            }).then(function (response) {
                if (!response.ok) throw new Error('Delete failed with HTTP ' + response.status);
                window.location.assign('/dashboard/history');
            }).catch(function (error) {
                document.getElementById('delete-result').textContent = error.message;
                deleteButton.disabled = false;
            });
        });
    }

})();
