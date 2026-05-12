(function () {
    const state = {
        user: null,
        peers: []
    };

    const els = {
        currentUser: document.getElementById("current-user"),
        trackerState: document.getElementById("tracker-state"),
        trackerNote: document.getElementById("tracker-note"),
        peerCount: document.getElementById("peer-count"),
        channelCount: document.getElementById("channel-count"),
        peerList: document.getElementById("peer-list"),
        registerForm: document.getElementById("register-form"),
        peerIp: document.getElementById("peer-ip"),
        peerPort: document.getElementById("peer-port"),
        channel: document.getElementById("channel"),
        actionStatus: document.getElementById("action-status"),
        heartbeat: document.getElementById("heartbeat"),
        leave: document.getElementById("leave"),
        refreshPeers: document.getElementById("refresh-peers"),
        logout: document.getElementById("logout")
    };

    async function api(path, options) {
        const response = await fetch(path, Object.assign({
            credentials: "include"
        }, options || {}));
        let data = {};
        try {
            data = await response.json();
        } catch (error) {
            data = {};
        }
        if (response.status === 401) {
            window.location.href = "/login.html";
            return null;
        }
        if (!response.ok) {
            throw new Error(data.message || `HTTP ${response.status}`);
        }
        return data;
    }

    function peerPayload() {
        return {
            peer_ip: els.peerIp.value.trim() || "127.0.0.1",
            peer_port: Number(els.peerPort.value),
            channels: [els.channel.value.trim() || "general"]
        };
    }

    function setStatus(message) {
        els.actionStatus.textContent = message;
    }

    function renderState(data) {
        if (!data) {
            return;
        }
        state.user = data.user;
        state.peers = data.peers || [];
        els.currentUser.textContent = `${data.user.username} (${data.user.role})`;
        els.trackerState.textContent = "Online";
        els.trackerState.classList.add("online");
        els.trackerNote.textContent = data.note;
        els.channelCount.textContent = String((data.channels || []).length);
        renderPeers(state.peers);
    }

    function renderPeers(peers) {
        els.peerCount.textContent = String(peers.length);
        els.peerList.textContent = "";
        if (!peers.length) {
            const empty = document.createElement("div");
            empty.className = "peer-card";
            empty.textContent = "No peers registered yet.";
            els.peerList.appendChild(empty);
            return;
        }
        peers.forEach((peer) => {
            const card = document.createElement("article");
            card.className = "peer-card";
            const channels = (peer.channels || []).join(", ") || "general";
            const socket = `${escapeHtml(peer.peer_ip)}:${peer.peer_port}`;
            const status = escapeHtml(peer.status);
            card.innerHTML = `
                <strong>${escapeHtml(peer.username)}</strong>
                <span><b>Socket:</b> ${socket}</span>
                <span><b>Status:</b>
                    <span class="status-pill online">${status}</span>
                </span>
                <span><b>Channels:</b> ${escapeHtml(channels)}</span>
            `;
            els.peerList.appendChild(card);
        });
    }

    async function loadMe() {
        const data = await api("/me");
        if (data) {
            state.user = data;
            els.currentUser.textContent = `${data.username} (${data.role})`;
        }
    }

    async function loadPeers() {
        const data = await api("/get-list");
        if (data) {
            state.peers = data.peers || [];
            renderPeers(state.peers);
        }
    }

    async function loadTrackerState() {
        const data = await api("/tracker-state");
        renderState(data);
    }

    async function registerPeer(event) {
        event.preventDefault();
        const payload = peerPayload();
        if (!payload.peer_port) {
            setStatus("Enter the listen port used by peer.py.");
            return;
        }
        const data = await api("/submit-info", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify(payload)
        });
        setStatus(data.message || "Peer registered.");
        await loadTrackerState();
    }

    async function heartbeat() {
        const payload = peerPayload();
        if (!payload.peer_port) {
            setStatus("Enter a peer port before sending heartbeat.");
            return;
        }
        await api("/heartbeat", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify(payload)
        });
        setStatus("Heartbeat sent.");
        await loadTrackerState();
    }

    async function leavePeer() {
        const payload = peerPayload();
        if (!payload.peer_port) {
            setStatus("Enter a peer port before leaving.");
            return;
        }
        await api("/leave", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify(payload)
        });
        setStatus("Peer marked offline.");
        await loadTrackerState();
    }

    async function logout() {
        await api("/logout", {method: "POST"});
        window.location.href = "/login.html";
    }

    function escapeHtml(value) {
        return String(value)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");
    }

    function bindEvents() {
        els.registerForm.addEventListener("submit", (event) => {
            registerPeer(event).catch((error) => setStatus(error.message));
        });
        els.heartbeat.addEventListener("click", () => {
            heartbeat().catch((error) => setStatus(error.message));
        });
        els.leave.addEventListener("click", () => {
            leavePeer().catch((error) => setStatus(error.message));
        });
        els.refreshPeers.addEventListener("click", () => {
            loadPeers().catch((error) => setStatus(error.message));
        });
        els.logout.addEventListener("click", () => {
            logout().catch((error) => setStatus(error.message));
        });
    }

    async function start() {
        bindEvents();
        await loadMe();
        await loadPeers();
        await loadTrackerState();
    }

    start().catch((error) => setStatus(error.message));
}());
